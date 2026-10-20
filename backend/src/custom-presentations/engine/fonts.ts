import { engineEnv } from "./runtime-context.js";
import { resolve, join } from "node:path";
export const presentationFontRoot = () =>
  resolve(engineEnv.PRESENTATION_FONT_DIR || join(process.cwd(), "fonts"));
