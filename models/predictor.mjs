import fs from 'node:fs/promises';
import {blank,validatePatch} from '../public/core.mjs';
import {coefficients} from '../public/targets.mjs';
import {keyForPatch} from './native-dataset.mjs';

export const PREDICTOR_VERSION='linear-predictor-v1';
const FEATURE_SIZE=64,LABEL_SIZE=31;
const finite=value=>typeof value==='number'&&Number.isFinite(value);

function featuresFromMagnitudes(values){const result=Array.from({length:FEATURE_SIZE},(_,i)=>values[i]??0),norm=Math.hypot(...result)||1;return result.map(value=>value/norm)}
function recordFeatures(record){const descriptor=record.notes?.find(note=>note.note===57)?.descriptor;if(!descriptor)throw Error('Predictor training needs an A3 native descriptor.');return featuresFromMagnitudes(descriptor.magnitude)}
function targetFeatures(target){const series=coefficients(target,FEATURE_SIZE);return featuresFromMagnitudes(series.sin.map((value,index)=>Math.hypot(value,series.cos[index])))}
function labelsFor(patch){const labels=[];for(const op of patch.operators)labels.push(op.coarse/31,op.fine/99,op.detune/14,op.mode,op.level/99);labels.push(patch.feedback/7);return labels}
function patchFromLabels(labels,algorithm){const patch=blank();patch.algorithm=algorithm;patch.feedback=Math.max(0,Math.min(7,Math.round(labels[LABEL_SIZE-1]*7)));patch.operators.forEach((op,index)=>{const offset=index*5;op.coarse=Math.max(0,Math.min(31,Math.round(labels[offset]*31)));op.fine=Math.max(0,Math.min(99,Math.round(labels[offset+1]*99)));op.detune=Math.max(0,Math.min(14,Math.round(labels[offset+2]*14)));op.mode=labels[offset+3]>=.5?1:0;op.level=Math.max(0,Math.min(99,Math.round(labels[offset+4]*99)));});return validatePatch(patch)}

function scoreLoss(weights,bias,x,y){let loss=0;for(let j=0;j<LABEL_SIZE;j++){let prediction=bias[j];for(let i=0;i<FEATURE_SIZE;i++)prediction+=weights[j][i]*x[i];loss+=(prediction-y[j])**2;}return loss/LABEL_SIZE}

/** Train a small local regression proposal model from native observations.
 * It is deliberately transparent and deterministic; the native runner still
 * remeasures every predicted patch before it can affect a cell. */
export function trainPredictor(dataset,{algorithm,epochs=240,learningRate=.08,weightDecay=.001}={}){
 if(!Number.isInteger(algorithm)||algorithm<1||algorithm>32)throw Error('Choose an algorithm from 1 through 32.');
 if(!Number.isInteger(epochs)||epochs<1||epochs>10000||!finite(learningRate)||learningRate<=0||learningRate>1)throw Error('Choose a bounded predictor training budget.');
 const examples=(dataset?.records??[]).filter(record=>record.patch?.algorithm===algorithm).map(record=>({x:recordFeatures(record),y:labelsFor(validatePatch(record.patch)),key:keyForPatch(record.patch)}));
 if(!examples.length)throw Error(`The dataset has no legal examples for algorithm ${algorithm}.`);
 const weights=Array.from({length:LABEL_SIZE},()=>Array(FEATURE_SIZE).fill(0)),bias=Array(LABEL_SIZE).fill(0);
 for(let j=0;j<LABEL_SIZE;j++)bias[j]=examples.reduce((sum,example)=>sum+example.y[j],0)/examples.length;
 for(let epoch=0;epoch<epochs;epoch++)for(const example of examples){
  const prediction=Array.from({length:LABEL_SIZE},(_,j)=>bias[j]+weights[j].reduce((sum,value,i)=>sum+value*example.x[i],0));
  for(let j=0;j<LABEL_SIZE;j++){const gradient=2*(prediction[j]-example.y[j])/LABEL_SIZE;bias[j]-=learningRate*gradient;for(let i=0;i<FEATURE_SIZE;i++)weights[j][i]-=learningRate*(gradient*example.x[i]+weightDecay*weights[j][i]);}
 }
 const loss=examples.reduce((sum,example)=>sum+scoreLoss(weights,bias,example.x,example.y),0)/examples.length;
 return {format:'dexfraggler-predictor',version:PREDICTOR_VERSION,feature:'normalized-native-harmonic-magnitude-v1',algorithm,weights,bias,training:{epochs,learningRate,weightDecay,examples:examples.length,loss,keys:examples.map(example=>example.key)}};
}

export function predictPatch(checkpoint,target){
 if(!checkpoint||checkpoint.format!=='dexfraggler-predictor'||checkpoint.version!==PREDICTOR_VERSION||!Number.isInteger(checkpoint.algorithm)||!Array.isArray(checkpoint.weights)||checkpoint.weights.length!==LABEL_SIZE||!Array.isArray(checkpoint.bias)||checkpoint.bias.length!==LABEL_SIZE)throw Error('Choose a DexFraggler predictor checkpoint.');
 const x=targetFeatures(target),labels=checkpoint.bias.map((value,j)=>value+checkpoint.weights[j].reduce((sum,weight,i)=>sum+weight*x[i],0));return patchFromLabels(labels,checkpoint.algorithm);
}

export async function savePredictor(filename,checkpoint){await fs.writeFile(filename,JSON.stringify(checkpoint,null,2)+'\n');return filename}
export async function loadPredictor(filename){return JSON.parse(await fs.readFile(filename,'utf8'))}
export {featuresFromMagnitudes,targetFeatures,labelsFor,patchFromLabels};
