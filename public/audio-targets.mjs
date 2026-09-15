// Local WAV preparation and imported periodic-target construction. This module
// is intentionally independent of React, Node Buffer, and the native runner so
// the same boundary can be used by browser imports, tests, and later workers.
export const AUDIO_PREPROCESS_VERSION='audio-prep-v1';
export const AUDIO_TARGET_VERSION='periodic-wave-v1';

const TAU=2*Math.PI;
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));
const powerOfTwo=value=>Number.isInteger(value)&&value>0&&(value&(value-1))===0;

function bytesOf(input){
  if(input instanceof Uint8Array)return input;
  if(input instanceof ArrayBuffer)return new Uint8Array(input);
  if(ArrayBuffer.isView(input))return new Uint8Array(input.buffer,input.byteOffset,input.byteLength);
  throw Error('Choose a WAV file or byte buffer.');
}
function ascii(bytes,start,length){return String.fromCharCode(...bytes.subarray(start,start+length))}
function u16(bytes,offset){return bytes[offset]|bytes[offset+1]<<8}
function u32(bytes,offset){return (bytes[offset]|bytes[offset+1]<<8|bytes[offset+2]<<16|bytes[offset+3]<<24)>>>0}
function i24(bytes,offset){const value=bytes[offset]|bytes[offset+1]<<8|bytes[offset+2]<<16;return value&0x800000?value-0x1000000:value}
function f32(bytes,offset){return new DataView(bytes.buffer,bytes.byteOffset+offset,4).getFloat32(0,true)}
function f64(bytes,offset){return new DataView(bytes.buffer,bytes.byteOffset+offset,8).getFloat64(0,true)}
function readText(bytes,start,length){return new TextDecoder().decode(bytes.subarray(start,start+length)).replace(/\0/g,'').trim()}

function hashText(value){
  let hash=2166136261;
  for(const character of value){hash^=character.charCodeAt(0);hash=Math.imul(hash,16777619)}
  return (hash>>>0).toString(16).padStart(8,'0');
}
function numberText(value){return Number(value).toPrecision(15)}

function parseInfoList(bytes,start,end){
  const info={};let offset=start;
  while(offset+8<=end){const id=ascii(bytes,offset,4),size=u32(bytes,offset+4),finish=Math.min(end,offset+8+size);if(id)info[id]=readText(bytes,offset+8,finish-(offset+8));offset=offset+8+size+(size&1)}
  return info;
}

function decodeSamples(bytes,dataStart,dataEnd,format){
  const {audioFormat,bitsPerSample,blockAlign,channels}=format;
  const bytesPerSample=Math.ceil(bitsPerSample/8),frameBytes=blockAlign||bytesPerSample*channels;
  if(![1,3].includes(audioFormat))throw Error(`Unsupported WAV audio format ${audioFormat}; use PCM or IEEE float.`);
  if(![8,16,24,32,64].includes(bitsPerSample))throw Error(`Unsupported WAV bit depth ${bitsPerSample}.`);
  if(frameBytes<bytesPerSample*channels||dataEnd<=dataStart)throw Error('The WAV data chunk is empty or malformed.');
  const frameCount=Math.floor((dataEnd-dataStart)/frameBytes),samples=new Array(frameCount);
  for(let frame=0;frame<frameCount;frame++){
    let sum=0;
    for(let channel=0;channel<channels;channel++){
      const offset=dataStart+frame*frameBytes+channel*bytesPerSample;let value;
      if(audioFormat===3){if(bitsPerSample===32)value=f32(bytes,offset);else if(bitsPerSample===64)value=f64(bytes,offset);else throw Error('IEEE float WAV files must use 32-bit or 64-bit samples.');}
      else if(bitsPerSample===8)value=(bytes[offset]-128)/128;
      else if(bitsPerSample===16){const raw=u16(bytes,offset);value=(raw&0x8000?raw-0x10000:raw)/32768;}
      else if(bitsPerSample===24)value=i24(bytes,offset)/8388608;
      else {const raw=(u32(bytes,offset));value=(raw&0x80000000?raw-0x100000000:raw)/2147483648;}
      if(!finite(value))throw Error('The WAV contains a non-finite sample.');
      sum+=value;
    }
    samples[frame]=sum/channels;
  }
  return samples;
}

/** Decode a RIFF/WAVE PCM or IEEE-float file into a mono sample stream. */
export function parseWav(input){
  const bytes=bytesOf(input);if(bytes.length<44||ascii(bytes,0,4)!=='RIFF'||ascii(bytes,8,4)!=='WAVE')throw Error('Import a RIFF/WAVE audio file.');
  let offset=12,format=null,data=null,info={},loops=[];
  while(offset+8<=bytes.length){
    const id=ascii(bytes,offset,4),size=u32(bytes,offset+4),start=offset+8,end=Math.min(bytes.length,start+size);
    if(id==='fmt '&&end-start>=16){const audioFormat=u16(bytes,start),channels=u16(bytes,start+2),sampleRate=u32(bytes,start+4),blockAlign=u16(bytes,start+12),bitsPerSample=u16(bytes,start+14);if(!channels||!sampleRate)throw Error('The WAV format chunk has invalid channels or sample rate.');format={audioFormat,channels,sampleRate,blockAlign,bitsPerSample};}
    else if(id==='data'&&!data)data={start,end};
    else if(id==='LIST'&&end-start>=4&&ascii(bytes,start,4)==='INFO')info={...info,...parseInfoList(bytes,start+4,end)};
    else if(id==='smpl'&&end-start>=36){const samplePeriod=u32(bytes,start+8),loopCount=u32(bytes,start+28);for(let i=0;i<loopCount&&start+36+i*24+24<=end;i++){const loop=start+36+i*24;loops.push({start:u32(bytes,loop+8),end:u32(bytes,loop+12),playCount:u32(bytes,loop+20)})}if(samplePeriod)info.samplePeriod=samplePeriod;}
    offset=start+size+(size&1);
  }
  if(!format)throw Error('The WAV has no format chunk.');if(!data)throw Error('The WAV has no audio data chunk.');
  const samples=decodeSamples(bytes,data.start,data.end,format),peak=Math.max(...samples.map(value=>Math.abs(value))),mean=samples.reduce((sum,value)=>sum+value,0)/Math.max(1,samples.length);
  const metadata={...info};
  const frameSize=Number(info.frameSize??info.framesize??info.wavetableFrameSize??info.wavetableframesize),frameCount=Number(info.frameCount??info.framecount??info.wavetableFrames??info.wavetableframes);
  if(Number.isInteger(frameSize)&&frameSize>0)metadata.frameSize=frameSize;if(Number.isInteger(frameCount)&&frameCount>0)metadata.frameCount=frameCount;
  if(loops.length)metadata.loops=loops;
  return {samples,sampleRate:format.sampleRate,channels:format.channels,format,metadata,peak,mean,sourceHash:hashText(`${format.sampleRate}|${format.channels}|${format.bitsPerSample}|${samples.map(numberText).join(',')}`)};
}

export function normalizeFrame(input){
  if(!Array.isArray(input)||input.length<2||input.some(value=>!finite(value)))throw Error('A waveform frame must contain at least two finite samples.');
  const mean=input.reduce((sum,value)=>sum+value,0)/input.length,centered=input.map(value=>value-mean),peak=Math.max(...centered.map(value=>Math.abs(value)));
  if(peak<1e-9)return {samples:centered.map(()=>0),dc:mean,peak,warning:'The frame is silent after DC removal.'};
  return {samples:centered.map(value=>value/peak),dc:mean,peak,warning:null};
}

function circularSample(samples,position){
  const n=samples.length,wrapped=((position%n)+n)%n,left=Math.floor(wrapped),fraction=wrapped-left;
  return samples[left]*(1-fraction)+samples[(left+1)%n]*fraction;
}
export function resamplePeriodic(input,size){
  if(!Number.isInteger(size)||size<2||size>65536)throw Error('Choose a periodic frame size from 2 to 65,536 samples.');
  return Array.from({length:size},(_,i)=>circularSample(input,i*input.length/size));
}

/** Align frames to a deterministic positive peak while retaining the offset. */
export function alignFrame(input,method='peak'){
  if(method==='none')return {samples:[...input],offset:0};
  if(method!=='peak')throw Error('Waveform alignment must be peak or none.');
  let index=0;for(let i=1;i<input.length;i++)if(Math.abs(input[i])>Math.abs(input[index]))index=i;
  return {samples:Array.from({length:input.length},(_,i)=>input[(i+index)%input.length]),offset:index};
}

export function harmonicCoefficients(input,maxHarmonics=Math.floor(input.length/2)-1){
  const n=input.length,h=Math.max(1,Math.min(Math.floor(n/2)-1,Math.floor(maxHarmonics))),sin=[],cos=[];
  for(let k=1;k<=h;k++){let s=0,c=0;for(let i=0;i<n;i++){const theta=TAU*k*i/n;s+=input[i]*Math.sin(theta);c+=input[i]*Math.cos(theta)}sin.push(2*s/n);cos.push(2*c/n)}
  return {sin,cos};
}

function frameQuality(input,periodSamples=null){
  const mean=input.reduce((sum,value)=>sum+value,0)/Math.max(1,input.length),energy=input.reduce((sum,value)=>sum+(value-mean)**2,0)/Math.max(1,input.length);
  let periodicity=null;if(finite(periodSamples)&&periodSamples>1&&periodSamples<input.length){const lag=Math.round(periodSamples);let a=0,b=0,c=0;for(let i=0;i+lag<input.length;i++){const x=input[i]-mean,y=input[i+lag]-mean;a+=x*x;b+=y*y;c+=x*y}periodicity=c/Math.sqrt(Math.max(a*b,1e-20));}
  return {rms:Math.sqrt(Math.max(0,energy)),peak:Math.max(...input.map(value=>Math.abs(value))),dc:mean,periodicity:periodicity===null?null:clamp(periodicity,-1,1)};
}

function estimateFundamental(samples,sampleRate,{minHz=40,maxHz=2000}={}){
  const n=Math.min(samples.length,16384),offset=Math.max(0,Math.floor((samples.length-n)/2)),mean=samples.slice(offset,offset+n).reduce((sum,value)=>sum+value,0)/Math.max(1,n),window=samples.slice(offset,offset+n).map(value=>value-mean),minLag=Math.max(2,Math.floor(sampleRate/maxHz)),maxLag=Math.min(n-2,Math.ceil(sampleRate/minHz));
  if(maxLag<=minLag)throw Error('The pitched sample is too short for the requested pitch range.');
  let bestLag=minLag,best=-Infinity;
  for(let lag=minLag;lag<=maxLag;lag++){
    let a=0,b=0,c=0;for(let i=0;i+lag<n;i++){const x=window[i],y=window[i+lag];a+=x*x;b+=y*y;c+=x*y}const correlation=c/Math.sqrt(Math.max(a*b,1e-20));if(correlation>best){best=correlation;bestLag=lag;}
  }
  return {frequency:sampleRate/bestLag,periodSamples:bestLag,periodicity:clamp(best,-1,1)};
}

function pitchedFrame(samples,sampleRate,options){
  const detected=finite(options.fundamentalHz)?{frequency:options.fundamentalHz,periodSamples:sampleRate/options.fundamentalHz,periodicity:null}:estimateFundamental(samples,sampleRate,options),period=detected.periodSamples,frameSize=options.frameSize??1024,cycles=Math.max(2,Math.min(32,Math.floor(options.cycles??8))),window=period*cycles;
  if(!finite(period)||period<2||window>samples.length*.9)throw Error('The pitched sample does not contain enough stable cycles for extraction.');
  const normalized=normalizeFrame(samples).samples;let bestStart=0,bestQuality=-Infinity;
  const limit=Math.max(0,normalized.length-Math.ceil(window));for(let start=0;start<=limit;start+=Math.max(1,Math.floor(period/2))){const quality=frameQuality(normalized.slice(start,start+Math.floor(window)),period).periodicity??-1;if(quality>bestQuality){bestQuality=quality;bestStart=start}}
  const result=Array.from({length:frameSize},(_,i)=>{const phase=i/frameSize;let sum=0;for(let cycle=0;cycle<cycles;cycle++)sum+=circularSample(normalized,bestStart+(cycle+phase)*period);return sum/cycles});
  return {samples:result,fundamentalHz:detected.frequency,periodSamples:period,periodicity:detected.periodicity??bestQuality,start:bestStart,cycles};
}

function frameFromSamples(samples,size,start=0){return Array.from({length:size},(_,i)=>samples[start+i]);}

function metadataNumber(metadata,keys){for(const key of keys){const value=Number(metadata?.[key]);if(Number.isInteger(value)&&value>0)return value}return null}

/**
 * Prepare a WAV as one or more normalized periodic frames. Wavetable imports
 * intentionally reject ambiguous lengths instead of silently chopping audio.
 */
export function prepareAudio(input,options={}){
  const wav=input?.samples&&finite(input.sampleRate)?input:parseWav(input),mode=options.mode??(options.pitchedSample?'pitched-sample':'auto'),metadata=wav.metadata??{};
  let selected=mode;if(selected==='auto')selected=metadataNumber(metadata,['frameCount','frames'])&&metadataNumber(metadata,['frameSize','framesize'])?'wavetable':'single-cycle';
  const warnings=[];if(wav.channels>1)warnings.push(`Downmixed ${wav.channels} input channels to mono.`);if(Math.abs(wav.mean)>1e-3)warnings.push('Removed DC offset during normalization.');if(wav.peak>1)warnings.push('Input clipped above full scale; normalized safely.');
  let frames=[],fundamentalHz=finite(options.fundamentalHz)?options.fundamentalHz:null,details={mode:selected};
  if(selected==='single-cycle'){
    const size=options.frameSize??metadataNumber(metadata,['frameSize','framesize','wavetableFrameSize']);
    if(size===null){if(!powerOfTwo(wav.samples.length))throw Error('Select a frame size for this single-cycle WAV; its length is not a power of two.');frames=[wav.samples];details.frameSize=wav.samples.length;}
    else {if(!Number.isInteger(size)||size<2||size>wav.samples.length)throw Error('The selected single-cycle frame size is invalid.');frames=[frameFromSamples(wav.samples,size)];details.frameSize=size;if(wav.samples.length!==size)warnings.push('Only the selected single-cycle frame was imported; trailing samples were not used.')}
  }else if(selected==='wavetable'){
    const frameSize=options.frameSize??metadataNumber(metadata,['frameSize','framesize','wavetableFrameSize']),frameCount=options.frameCount??metadataNumber(metadata,['frameCount','framecount','wavetableFrames','frames']);
    if(frameSize===null&&frameCount===null)throw Error('Select a wavetable frame size or frame count; the WAV metadata is insufficient.');
    if(frameSize!==null&&!Number.isInteger(frameSize)||frameSize!==null&&frameSize<2)throw Error('Choose a valid wavetable frame size.');
    if(frameCount!==null&&!Number.isInteger(frameCount)||frameCount!==null&&frameCount<1)throw Error('Choose a valid wavetable frame count.');
    const size=frameSize??Math.floor(wav.samples.length/frameCount),count=frameCount??Math.floor(wav.samples.length/size);
    if(size*count!==wav.samples.length)throw Error('Wavetable frame size and count must cover the complete WAV without remainder.');
    frames=Array.from({length:count},(_,i)=>frameFromSamples(wav.samples,size,i*size));details.frameSize=size;details.frameCount=count;
  }else if(selected==='pitched-sample'){
    const extracted=pitchedFrame(wav.samples,wav.sampleRate,{...options,frameSize:options.frameSize??1024});frames=[extracted.samples];fundamentalHz=extracted.fundamentalHz;details={...details,...extracted};if(extracted.periodicity!==null&&extracted.periodicity<.75)warnings.push(`Weak periodicity detected (${extracted.periodicity.toFixed(3)}); choose a cleaner sustained sample.`);
  }else throw Error('Choose single-cycle, wavetable, or pitched-sample input.');
  if(!frames.length)throw Error('No waveform frames were found.');
  const prepared=frames.map((frame,index)=>{const normalized=normalizeFrame(resamplePeriodic(frame,options.outputSize??1024)),aligned=alignFrame(normalized.samples,options.alignment??'peak'),quality=frameQuality(aligned.samples,details.periodSamples??null);if(normalized.warning)warnings.push(`Frame ${index+1}: ${normalized.warning}`);return {samples:aligned.samples,alignmentOffset:aligned.offset,quality}});
  const framesForTargets=distributeFrames(prepared,32),source={mode:selected,sourceHash:wav.sourceHash,frameCount:prepared.length,frameSize:prepared[0].samples.length,name:String(options.name??'Imported audio').slice(0,120),preprocessVersion:AUDIO_PREPROCESS_VERSION};
  const targets=framesForTargets.map((frame,index)=>createPeriodicTarget(frame.samples,{sampleRate:wav.sampleRate,fundamentalHz:fundamentalHz??(finite(options.defaultFundamentalHz)?options.defaultFundamentalHz:220),source:{...source,frameIndex:index,interpolated:frame.interpolated,position:frame.position},alignmentOffset:frame.alignmentOffset}));
  return {mode:selected,sampleRate:wav.sampleRate,sourceHash:wav.sourceHash,frames:prepared,targets,warnings:[...new Set(warnings)],details};
}

export function distributeFrames(frames,count=32){
  if(!Array.isArray(frames)||!frames.length||!Number.isInteger(count)||count<1)throw Error('Distribute at least one source frame across a positive column count.');
  if(frames.length===1)return Array.from({length:count},()=>({...frames[0],position:0,interpolated:false}));
  return Array.from({length:count},(_,slot)=>{const position=slot*(frames.length-1)/Math.max(1,count-1),left=Math.floor(position),fraction=position-left;if(fraction===0)return {...frames[left],position,interpolated:false};const right=frames[Math.min(frames.length-1,left+1)],samples=frames[left].samples.map((value,i)=>value*(1-fraction)+right.samples[i]*fraction),normalized=normalizeFrame(samples),aligned=alignFrame(normalized.samples,'peak');return {...frames[left],samples:aligned.samples,alignmentOffset:aligned.offset,position,interpolated:true,quality:frameQuality(aligned.samples)};});
}

export function createPeriodicTarget(samples,{sampleRate=48000,fundamentalHz=220,source={},alignmentOffset=0,maxHarmonics=255}={}){
  const normalized=normalizeFrame(resamplePeriodic(samples,samples.length)),harmonics=harmonicCoefficients(normalized.samples,maxHarmonics),target={kind:AUDIO_TARGET_VERSION,samples:normalized.samples,sampleRate,fundamentalHz,harmonics,source:{...source,alignmentOffset},preprocessVersion:AUDIO_PREPROCESS_VERSION};
  target.id=hashText(`${target.kind}|${target.preprocessVersion}|${sampleRate}|${fundamentalHz}|${target.samples.map(numberText).join(',')}|${harmonics.sin.map(numberText).join(',')}|${harmonics.cos.map(numberText).join(',')}`);
  return target;
}

export function previewFrames(frames,size=128){return frames.map(frame=>resamplePeriodic(frame.samples??frame,size))}
