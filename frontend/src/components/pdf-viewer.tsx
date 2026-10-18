'use client';

import { useEffect, useRef, useState } from 'react';
import { CaretLeft, CaretRight, DownloadSimple, FilePdf, FileText, Minus, Plus, SpinnerGap, WarningCircle } from '@phosphor-icons/react';
import type { PDFDocumentProxy, PDFDocumentLoadingTask, RenderTask } from 'pdfjs-dist';
import styles from './pdf-viewer.module.css';

export default function PdfViewer({url,title,page=1,filename='document.pdf'}:{url:string;title:string;page?:number;filename?:string}) {
  const [document,setDocument]=useState<PDFDocumentProxy|null>(null);
  const [currentPage,setCurrentPage]=useState(page);
  const [zoom,setZoom]=useState(0);
  const [width,setWidth]=useState(500);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  const [text,setText]=useState<string|null>(null);
  const [image,setImage]=useState(false);
  const [accessibleText,setAccessibleText]=useState('');
  const canvas=useRef<HTMLCanvasElement>(null);
  const viewport=useRef<HTMLDivElement>(null);
  useEffect(()=>setCurrentPage(page),[page,url]);
  useEffect(()=>{
    const element=viewport.current;
    if(!element)return;
    const observer=new ResizeObserver(entries=>setWidth(entries[0].contentRect.width));
    observer.observe(element);
    return()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    let alive=true;
    let loadingTask:PDFDocumentLoadingTask|undefined;
    const abort=new AbortController();
    setDocument(null);setError('');setLoading(true);setText(null);setImage(false);
    void(async()=>{
      try{
        const response=await fetch(url,{signal:abort.signal});
        if(!response.ok)throw new Error(`Source could not be loaded (${response.status}).`);
        const contentType=response.headers.get('content-type') || '';
        if(contentType.startsWith('image/')){if(alive){setImage(true);setLoading(false);}return;}
        if(!filename.toLowerCase().endsWith('.pdf') && !contentType.includes('pdf')){
          const content=await response.text();
          if(alive){setText(content);setLoading(false);}return;
        }
        const pdfjs=await import('pdfjs-dist');
        pdfjs.GlobalWorkerOptions.workerSrc='/pdfjs/pdf.worker.min.mjs';
        const bytes=new Uint8Array(await response.arrayBuffer());
        if(!alive)return;
        loadingTask=pdfjs.getDocument({data:bytes,useSystemFonts:true,standardFontDataUrl:'/pdfjs/standard_fonts/'});
        const pdf=await loadingTask.promise;
        if(!alive){await loadingTask.destroy();return;}
        setDocument(pdf);setLoading(false);
      }catch(cause){if(alive && !abort.signal.aborted){setError(cause instanceof Error?cause.message:'Unable to read this publication.');setLoading(false);}}
    })();
    return()=>{alive=false;abort.abort();if(loadingTask)void loadingTask.destroy();};
  },[url,filename]);
  useEffect(()=>{
    if(!document || !canvas.current)return;
    let alive=true;
    let task:RenderTask|undefined;
    void(async()=>{
      try{
        const pdfPage=await document.getPage(Math.min(Math.max(currentPage,1),document.numPages));
        if(!alive || !canvas.current)return;
        const unscaled=pdfPage.getViewport({scale:1});
        const scale=zoom || Math.max(.2,(width-40)/unscaled.width);
        const view=pdfPage.getViewport({scale});
        const pixelRatio=Math.min(window.devicePixelRatio || 1,2);
        const surface=canvas.current;
        surface.width=Math.floor(view.width*pixelRatio);surface.height=Math.floor(view.height*pixelRatio);
        surface.style.width=`${view.width}px`;surface.style.height=`${view.height}px`;
        const context=surface.getContext('2d',{alpha:false});
        if(!context)throw new Error('Canvas rendering is unavailable.');
        task=pdfPage.render({canvas:surface,canvasContext:context,viewport:view,transform:[pixelRatio,0,0,pixelRatio,0,0]});
        await task.promise;
        const content=await pdfPage.getTextContent();
        if(alive)setAccessibleText(content.items.map(item=>'str' in item?item.str:'').join(' '));
      }catch(cause){
        if(alive && !(cause instanceof Error && cause.name==='RenderingCancelledException'))setError(cause instanceof Error?cause.message:'Page could not be rendered.');
      }
    })();
    return()=>{alive=false;task?.cancel();};
  },[document,currentPage,zoom,width]);
  const pages=document?.numPages || 1;
  const pdfControls=Boolean(document) || filename.toLowerCase().endsWith('.pdf');
  return <div className={styles.viewer} aria-label={`${title} document viewer`}>
    <div className={styles.toolbar}>
      {pdfControls?<FilePdf size={15}/>:<FileText size={15}/>}
      {pdfControls?<>
      <button type="button" aria-label="Previous PDF page" disabled={!document || currentPage<=1} onClick={()=>setCurrentPage(value=>Math.max(1,value-1))}><CaretLeft size={14}/></button>
      <span className={styles.pageCount} aria-live="polite">{currentPage} <span>/ {pages}</span></span>
      <button type="button" aria-label="Next PDF page" disabled={!document || currentPage>=pages} onClick={()=>setCurrentPage(value=>Math.min(pages,value+1))}><CaretRight size={14}/></button>
      <span className={styles.divider}/>
      <button type="button" aria-label="Zoom out PDF" disabled={!document} onClick={()=>setZoom(value=>Math.max(.25,(value || .8)-.15))}><Minus size={13}/></button>
      <select aria-label="PDF zoom" disabled={!document} value={zoom} onChange={event=>setZoom(Number(event.target.value))}>
        <option value={0}>Fit width</option>{[.5,.75,1,1.25,1.5,2].map(value=><option value={value} key={value}>{value*100}%</option>)}
        {zoom!==0 && ![.5,.75,1,1.25,1.5,2].includes(zoom)?<option value={zoom}>{Math.round(zoom*100)}%</option>:null}
      </select>
      <button type="button" aria-label="Zoom in PDF" disabled={!document} onClick={()=>setZoom(value=>Math.min(3,(value || .8)+.15))}><Plus size={13}/></button>
      </>:<span>Original source</span>}
      <a href={url} download={filename} aria-label="Download original source" className={styles.download}><DownloadSimple size={14}/></a>
    </div>
    <div className={styles.viewport} ref={viewport}>
      {loading?<div className={styles.message}><SpinnerGap size={22} className="spin"/><span>Loading publication</span></div>:null}
      {error?<div className={styles.message} role="alert"><WarningCircle size={22}/><strong>Could not render this source</strong><span>{error}</span><a href={url} target="_blank" rel="noreferrer">Open original file</a></div>:null}
      {!loading && !error && text!==null?<pre className={styles.textSource}>{text}</pre>:null}
      {!loading && !error && image?<img className={styles.imageSource} src={url} alt={title}/>:null}
      <canvas ref={canvas} className={styles.page} style={{display:document && !error?'block':'none'}} role="img" aria-label={`${title}, page ${currentPage}`}/>
      <span className={styles.accessibleText}>{accessibleText}</span>
    </div>
  </div>;
}
