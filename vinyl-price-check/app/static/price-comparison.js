/* Pure comparisons: requested prices stay on the visitor's device. */
(function(root){
 'use strict';
 function parse(value){
  if(value==null||String(value).trim()==='')return null;
  const raw=String(value).trim();
  if(!/^\d{1,7}(?:[.,]\d{1,2})?$/.test(raw))return NaN;
  const amount=Number(raw.replace(',','.'));
  return Number.isFinite(amount)&&amount>0&&amount<=1000000?amount:NaN;
 }
 function difference(asked,item){
  if(!Number.isFinite(asked)||asked<=0||item?.compatibility!=='compatible'||item.price?.currency!=='EUR')return null;
  const value=Number(item.price.value);
  if(!Number.isFinite(value)||value<=0)return null;
  const euros=Math.round((asked-value)*100)/100;
  return {euros,percent:Math.round(euros/value*100),direction:euros>0?'above':euros<0?'below':'equal'};
 }
 function compare(asked,data){
  if(asked===null)return null;
  if(!Number.isFinite(asked)||asked<=0)return {state:'invalid'};
  if(data?.status!=='ok')return {state:'unavailable',count:0};
  const count=(data.items||[]).filter(item=>difference(asked,item)!==null).length;
  const price=data.price||{};
  const low=price.low,high=price.high;
  if(price.available===true&&price.currency==='EUR'&&count>=3&&price.count>=3&&Number.isFinite(low)&&Number.isFinite(high)&&low>0&&high>=low){
   return {state:asked<low?'below':asked>high?'above':'inline',count:price.count,low,high,
    medianDifference:Number.isFinite(price.median)&&price.median>0?Math.round((asked-price.median)/price.median*100):null};
  }
  return {state:count?'limited':'unavailable',count};
 }
 root.FirstPressPrices={parse,difference,compare};
})(globalThis);
