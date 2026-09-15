import path from 'node:path';
import {readNativeDataset} from '../models/native-dataset.mjs';
import {savePredictor,trainPredictor} from '../models/predictor.mjs';

function argument(name,fallback=null){const index=process.argv.indexOf(name);return index>=0?process.argv[index+1]??fallback:fallback}
function required(name){const value=argument(name);if(!value)throw Error(`Missing ${name}.`);return value}
const datasetPath=required('--dataset'),outputPath=required('--out'),algorithm=Number(required('--algorithm')),epochs=Number(argument('--epochs','240'));
const checkpoint=trainPredictor(await readNativeDataset(datasetPath),{algorithm,epochs});await savePredictor(path.resolve(outputPath),checkpoint);console.log(JSON.stringify({out:path.resolve(outputPath),algorithm,examples:checkpoint.training.examples,loss:checkpoint.training.loss}));
