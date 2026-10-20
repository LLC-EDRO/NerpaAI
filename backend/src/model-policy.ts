import {inferenceConfiguration} from './inference-provider.js';

export type AvailableModel = {
  id: string;
  name: string;
  sizeB: number;
  license: string;
  text: boolean;
  vision: boolean;
};

/** The server uses the model supplied for this inference provider. */
export function eligibleModel(raw: any): AvailableModel | undefined {
  const id = raw?.id;
  if (typeof id !== 'string' || id !== inferenceConfiguration().model) return;
  return { id, name: id, sizeB: 27, license: '', text: true, vision: true };
}
