// Only static original artwork is cached; world state always comes from the server.
const CACHE='living-kanto-artwork-v1';
async function artwork(url){
 let cache;try{cache=await caches.open(CACHE);const hit=await cache.match(url);if(hit)return hit;}catch(_){}
 const response=await fetch(url);if(!response.ok)throw Error('Artwork unavailable: '+url);
 if(cache)try{await cache.put(url,response.clone());}catch(_){}
 return response;
}
export async function cachedJSON(url){return (await artwork(url)).json();}
export async function cachedImage(url){
 const blob=await (await artwork(url)).blob(),source=URL.createObjectURL(blob),image=new Image();
 try{await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(Error('Artwork could not be decoded: '+url));image.src=source;});return image;}
 finally{URL.revokeObjectURL(source);}
}
