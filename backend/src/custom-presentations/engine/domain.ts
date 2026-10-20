import {z} from 'zod';
import {visualKinds,type VisualSlot} from './visual-types.js';
import type {PresentationResearch} from './research.js';
import type {SourceFigureEvidence} from './source-figure-evidence.js';
import type {HtmlGenerationProgress} from './html-progress.js';
import {dataSourceSchema,dataChartKinds} from './data-contract.js';
export const briefSchema = z.object({
  topic: z.string().trim().min(3).max(1500),
  count: z.number().int().min(1).max(40),
  sourceText: z.string().max(60000).default(""),
  webSearch: z.boolean().default(true),
  dataSources:z.array(dataSourceSchema).max(6).optional(),
  sourceDocument:z.object({version:z.literal(1),blocks:z.array(z.unknown()).optional(),images:z.array(z.object({id:z.string(),name:z.string(),assetId:z.string().optional(),caption:z.string().optional()})),warnings:z.array(z.string())}).optional(),
});
export const planSchema = z.object({
  slides: z
    .array(
      z.object({
        id: z.string().optional(),
        sourceLayoutId: z.string(),
        title: z.string().trim().min(1).max(200),
        brief: z.string().trim().min(1).max(2000),
        dataViewId:z.string().max(100).optional(),
        visualPlan:z.object({kind:z.enum(['text','chart','table','diagram','metrics']),chartType:z.enum(dataChartKinds).optional(),description:z.string().trim().min(1).max(600)}).optional(),
        sourceImageIds:z.array(z.string().max(100)).max(80).optional(),
        images: z.array(z.object({
          slotIndex: z.number().int().min(0).max(79),
          kind: z.enum(visualKinds),
          source: z.enum(['auto','web']).optional(),
          searchQuery: z.string().trim().min(3).max(160).optional(),
          background: z.enum(['transparent', 'opaque']),
          description: z.string().trim().min(1).max(700),
        })).max(80).optional().catch(undefined),
      }),
    )
    .min(1)
    .max(40),
});
export type Outline = z.infer<typeof planSchema>;
export type Brief = z.infer<typeof briefSchema> & {instructions?:string};
export interface Layout {
  id: string;
  index: number;
  name: string;
  usable: boolean;
  warnings: string[];
  slots: Slot[];
  charts: any[];
  visualSlots?: VisualSlot[];
  [key: string]: any;
}
export interface Slot {
  key: string;
  text: string;
  shapeId: number;
  role: string;
  maxChars: number;
  size: number;
  x: number;
  y: number;
  w: number;
  h: number;
  [key: string]: any;
}
export interface Project {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  revision: number;
  status: string;
  message: string;
  busy: boolean;
  progress?: { done: number; total: number };
  htmlProgress?: HtmlGenerationProgress;
  brief?: Brief;
  sourceFigureEvidence?: SourceFigureEvidence;
  research?: PresentationResearch;
  researchWarning?: string;
  planWarnings?: Array<{slide:number;reason:string;message:string}>;
  analysis?: any;
  plan?: Outline;
  result?: {
    warnings?: Array<{slide?: number; key?: string; reason: string; message: string}>;
    pdfAvailable?: boolean;
    slides: number;
  };
  error?: { code: string; message: string; details?: unknown };
  lastAction?: string;
  events: Array<{ at: string; message: string }>;
}
