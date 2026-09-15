import test from 'node:test';
import assert from 'node:assert/strict';
import {blank,validatePatch} from '../public/core.mjs';
import {idealTarget} from '../public/targets.mjs';
import {nativeObservation} from '../models/native-dataset.mjs';
import {predictPatch,trainPredictor} from '../models/predictor.mjs';

function capture(){return {sampleRate:48000,velocity:100,offsetSamples:7200,captureSamples:4096,notes:[45,57,69],waveforms:[45,57,69].map(note=>Array.from({length:4096},(_,i)=>Math.sin(2*Math.PI*(440*2**((note-69)/12))*i/48000)))}};
function record(feedback){const patch=blank();patch.algorithm=1;patch.feedback=feedback;patch.operators[0].level=80+feedback;return nativeObservation(patch,capture(),{includeWaveforms:false})}

test('trained local predictor emits legal algorithm-specific proposals for imported targets',()=>{
 const checkpoint=trainPredictor({records:[record(0),record(1)]},{algorithm:1,epochs:8});assert.equal(checkpoint.version,'linear-predictor-v1');assert.equal(checkpoint.training.examples,2);
 const proposal=predictPatch(checkpoint,idealTarget('sine'));assert.equal(proposal.algorithm,1);assert.doesNotThrow(()=>validatePatch(proposal));
});
