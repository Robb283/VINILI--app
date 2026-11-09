const photoDialog=document.getElementById('photo-viewer');
const viewerImage=document.getElementById('viewer-image');
const viewerStage=document.getElementById('viewer-stage');
let viewerEdition=null,viewerIndex=0,viewerZoom=1,viewerOpener=null;
function applyViewerZoom(){
  if(!viewerImage.naturalWidth)return;
  const base=Math.min((viewerStage.clientWidth-32)/viewerImage.naturalWidth,(viewerStage.clientHeight-32)/viewerImage.naturalHeight,1);
  viewerImage.style.width=Math.max(1,Math.round(viewerImage.naturalWidth*base*viewerZoom))+'px';
  viewerImage.style.height=Math.max(1,Math.round(viewerImage.naturalHeight*base*viewerZoom))+'px';
  document.getElementById('viewer-zoom-label').textContent=viewerZoom===1?'Adatta':Math.round(viewerZoom*100)+'%';
  document.getElementById('viewer-zoom-out').disabled=viewerZoom<=1;
  document.getElementById('viewer-zoom-in').disabled=viewerZoom>=4;
}
function showViewerImage(index){
  if(!viewerEdition?.images.length)return;
  viewerIndex=(index+viewerEdition.images.length)%viewerEdition.images.length;
  viewerZoom=1;viewerStage.scrollTo(0,0);viewerImage.style.width='';viewerImage.style.height='';
  viewerImage.hidden=false;document.getElementById('viewer-error').hidden=true;
  document.getElementById('viewer-title').textContent=viewerEdition.title+' · '+countryName(viewerEdition.country)+' · '+(viewerEdition.year||'anno non indicato');
  document.getElementById('viewer-counter').textContent=`Foto ${viewerIndex+1} di ${viewerEdition.images.length}`;
  viewerImage.alt=`Foto ${viewerIndex+1} di ${viewerEdition.title}, edizione ${viewerEdition.country||''} ${viewerEdition.year||''}`;
  viewerImage.src=viewerEdition.images[viewerIndex].url;
  document.getElementById('viewer-prev').disabled=viewerEdition.images.length<2;
  document.getElementById('viewer-next').disabled=viewerEdition.images.length<2;
  document.getElementById('viewer-zoom-label').textContent='Adatta';
  document.getElementById('viewer-zoom-out').disabled=true;
  document.getElementById('viewer-zoom-in').disabled=false;
  if(viewerImage.complete&&viewerImage.naturalWidth)applyViewerZoom();
}
function openPhotoViewer(edition,index=0){
  viewerEdition=edition;viewerOpener=document.activeElement;
  if(!photoDialog.open)photoDialog.showModal();
  document.body.classList.add('photo-viewer-open');
  showViewerImage(index);
}
function zoomViewer(delta){viewerZoom=Math.max(1,Math.min(4,viewerZoom+delta));applyViewerZoom();}
viewerImage.onload=applyViewerZoom;
viewerImage.onerror=()=>{viewerImage.hidden=true;document.getElementById('viewer-error').hidden=false;};
viewerImage.ondblclick=()=>{viewerZoom=viewerZoom===1?2:1;applyViewerZoom();};
document.getElementById('viewer-close').onclick=()=>photoDialog.close();
document.getElementById('viewer-prev').onclick=()=>showViewerImage(viewerIndex-1);
document.getElementById('viewer-next').onclick=()=>showViewerImage(viewerIndex+1);
document.getElementById('viewer-zoom-in').onclick=()=>zoomViewer(.5);
document.getElementById('viewer-zoom-out').onclick=()=>zoomViewer(-.5);
document.getElementById('viewer-fit').onclick=()=>{viewerZoom=1;applyViewerZoom();viewerStage.scrollTo(0,0);};
photoDialog.addEventListener('close',()=>{document.body.classList.remove('photo-viewer-open');if(viewerOpener?.isConnected)viewerOpener.focus({preventScroll:true});});
photoDialog.addEventListener('click',event=>{if(event.target===photoDialog)photoDialog.close();});
photoDialog.addEventListener('keydown',event=>{
  if(event.key==='ArrowRight'){event.preventDefault();showViewerImage(viewerIndex+1);}
  else if(event.key==='ArrowLeft'){event.preventDefault();showViewerImage(viewerIndex-1);}
  else if(event.key==='+'||event.key==='='){event.preventDefault();zoomViewer(.5);}
  else if(event.key==='-'){event.preventDefault();zoomViewer(-.5);}
  else if(event.key==='0'){event.preventDefault();viewerZoom=1;applyViewerZoom();viewerStage.scrollTo(0,0);}
});
window.addEventListener('resize',()=>{if(photoDialog.open)applyViewerZoom();});
