import {prepareAudio} from './audio-targets.mjs';

self.onmessage=event=>{
  try{self.postMessage({ok:true,result:prepareAudio(event.data.buffer,event.data.options??{})})}
  catch(error){self.postMessage({ok:false,error:error instanceof Error?error.message:'Unable to prepare audio.'})}
};
