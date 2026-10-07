"""Signed local checkout bridge; prices and ownership checked by backend."""
import hashlib,hmac,json,time,os,re,base64,fcntl
from pathlib import Path
from datetime import UTC,datetime
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter,Request,HTTPException
from sqlalchemy import update
from app.config import get_settings
from app.db.session import sessions
from app.db.models import User,Payment,SupportTicket,SaleOrder,Plan
from app.core.security import TokenVault
from app.services.commerce import CommerceService
from app.services.requests import select_tariff
from app.services.portal import ensure_order
router=APIRouter()

def key():return os.environ['AERA_CHECKOUT_BRIDGE_KEY'].encode()
def intent(order_id,user_id):
 data=base64.urlsafe_b64encode(json.dumps({'order_id':order_id,'user_id':user_id,'exp':int(time.time())+1800},separators=(',',':')).encode()).decode().rstrip('=')
 return data+'.'+hmac.new(key(),data.encode(),hashlib.sha256).hexdigest()
def verify_intent(value):
 try:
  data,sig=value.split('.')
  if not hmac.compare_digest(sig,hmac.new(key(),data.encode(),hashlib.sha256).hexdigest()):raise ValueError()
  result=json.loads(base64.urlsafe_b64decode(data+'='*(-len(data)%4)))
  if result['exp']<time.time():raise ValueError()
  return result
 except Exception:raise HTTPException(403,'Ссылка оплаты истекла. Выберите тариф заново.') from None

def nonce():
 path=Path('/opt/aera/.fk-api-nonce')
 with path.open('a+') as f:
  fcntl.flock(f,fcntl.LOCK_EX);f.seek(0);old=int(f.read() or '0')
  value=max(time.time_ns()//1000,old+1);f.seek(0);f.truncate();f.write(str(value));f.flush()
  return value

async def api_call(endpoint,**fields):
 settings=get_settings();data={**fields,'shopId':int(settings.freekassa_merchant_id),'nonce':nonce()}
 data['signature']=hmac.new(os.environ['FREEKASSA_API_KEY'].encode(),'|'.join(str(data[k]) for k in sorted(data)).encode(),hashlib.sha256).hexdigest()
 async with httpx.AsyncClient(timeout=20) as client:
  response=await client.post('https://api.fk.life/v1/'+endpoint,json=data)
  result=response.json()
 if response.status_code!=200 or result.get('type')!='success':
  raise HTTPException(502,'FreeKassa пока не открыла этот способ оплаты. Попробуйте другой способ или обратитесь в поддержку.')
 return result

@router.post('/internal/web-checkout')
async def checkout(request:Request):
 if request.client.host not in {'127.0.0.1','::1'}:raise HTTPException(403)
 raw=await request.body()
 if len(raw)>4096:raise HTTPException(400)
 stamp=request.headers.get('x-aera-time','')
 try:valid=abs(time.time()-int(stamp))<30
 except ValueError:valid=False
 expected=hmac.new(key(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
 if not valid or not hmac.compare_digest(expected,request.headers.get('x-aera-sign','')):raise HTTPException(403)
 data=json.loads(raw);method=str(data.get('method','36'))
 if data.get('action') == 'summary':
  proof=verify_intent(data.get('intent',''))
  async with sessions() as db:
   order=await db.get(SaleOrder,proof['order_id'])
   ticket=await db.get(SupportTicket,order.ticket_id) if order else None
   if not ticket or ticket.user_id!=proof['user_id']:raise HTTPException(403)
   plan=await db.get(Plan,order.plan_id)
   return {'name':plan.name,'duration_months':plan.duration_months,'duration_days':plan.duration_days,'price_minor':order.amount_rub_minor}

 if method not in {'36','42'}:raise HTTPException(400)
 email=data.get('email','').strip()
 if not re.fullmatch(r'[^\s@]{1,128}@[^\s@.]+(?:\.[^\s@.]+)+',email) or len(email)>254:raise HTTPException(400,'Укажите email для платёжной квитанции.')
 if data.get('accepted') is not True:raise HTTPException(400,'Примите условия покупки.')
 methods=(await api_call('currencies'))['currencies']
 selected=next((m for m in methods if str(m['id'])==method and m['is_enabled']),None)
 if not selected:raise HTTPException(409,'Этот способ ещё не подключён в кассе. Выберите карту.')
 if float(selected['fee'].get('user',0))!=0:raise HTTPException(503,'Приём оплаты временно настраивается: комиссия должна быть включена в цену тарифа.')
 settings=get_settings()
 async with sessions.begin() as db:
  proof=verify_intent(data['intent']) if data.get('intent') else None
  uid=proof['user_id'] if proof else data.get('user_id')
  await db.execute(update(User).where(User.id==uid).values(is_active=User.is_active))
  user=await db.get(User,uid,populate_existing=True)
  if not user or not user.is_active or user.is_blocked:raise HTTPException(403)
  if proof:
   order=await db.get(SaleOrder,proof['order_id'])
   ticket=await db.get(SupportTicket,order.ticket_id) if order else None
   if not ticket or ticket.user_id!=uid or order.paid_at:raise HTTPException(409)
  else:
   ticket,plan=await select_tariff(db,CommerceService(db,TokenVault(settings.app_secret)),user,data.get('plan_id'),settings.admin_ids,notify_owner=False)
   order=await ensure_order(db,ticket,plan)
  if order.amount_rub_minor > 1000000:raise HTTPException(400,"Максимальная сумма заказа — 10 000 ₽.")
  user.terms_accepted_at=datetime.now(UTC);user.terms_version='portal-2'
  payment=await db.get(Payment,order.payment_id) if order.payment_id else None
  if payment and (payment.provider!='freekassa' or payment.status!='PENDING'):raise HTTPException(409,'У вас уже открыт другой способ оплаты. Отмените неоплаченный заказ в боте.')
  if payment and payment.details.get('api_url'):return {'url':payment.details['api_url']}
  if payment and payment.details.get('api_pending') and time.time()-payment.details.get('api_started_at',0)<60:raise HTTPException(409,'Счёт создаётся. Повторите через минуту.')
  from app.services.paid_pool import reserve,enabled
  if not await enabled(db) or await reserve(db,order) is None:raise HTTPException(409,'Тариф временно недоступен.')
  if not payment:
   payment=Payment(user_id=uid,plan_id=order.plan_id,provider='freekassa',amount_minor=order.amount_rub_minor,currency='RUB',details={'manual_order':order.id})
   db.add(payment);await db.flush();order.payment_id=payment.id;payment.provider_payment_id='fk-order:'+payment.id
  # Persist intent before network request. Uncertain outcomes retain the reserved key.
  payment.details={**payment.details,'external_started':True,'method':method,'api_pending':True,'api_started_at':time.time()}
  pid,amount=payment.id,payment.amount_minor
 # Recover an uncertain attempt before creating another external invoice.
 orders=await api_call('orders',paymentId=pid)
 previous=next((o for o in orders.get('orders',[]) if str(o.get('merchant_order_id'))==pid),None)
 if previous and int(previous.get('status',0))==1:raise HTTPException(409,'Оплата получена. Ожидаем подтверждение платёжной системы.')
 result=await api_call('orders/create',paymentId=pid,i=int(method),email=email,ip=data.get('peer_ip'),amount=f'{amount//100}.{amount%100:02d}',currency='RUB')
 location=result.get('location','');parsed=urlsplit(location)
 if parsed.scheme!='https' or parsed.hostname not in {'pay.freekassa.net','pay.freekassa.ru','fmt.me','pay.fk.money','pay.fk.life'} or parsed.username:raise HTTPException(502)
 async with sessions.begin() as db:
  payment=await db.get(Payment,pid)
  payment.details={**payment.details,'api_url':location,'api_order_id':str(result.get('orderId','')),'api_pending':False}
 return {'url':location}
