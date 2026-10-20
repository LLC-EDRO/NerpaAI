export const visualKinds = [
  "illustration",
  "photo",
  "diagram",
  "chart",
  "interface",
] as const;

export type VisualSlot = {
  shapeId: number;
  kind: "picture" | "placeholder";
  box: { x: number; y: number; w: number; h: number };
  aspectRatio: number;
  sourceRole: string;
  protected: boolean;
  requiresOpaque: boolean;
  name?: string;
  detection?: {
    method: "explicit_image_instruction";
    markerFieldKeys: string[];
    markerShapeIds: number[];
    labels: string[];
  };
};

export function visualPreserveReason(
  choice: {slot:VisualSlot;role:string},
  dimensions: { width: number; height: number },
) {
  const { slot, role } = choice;
  if (slot.sourceRole === "icon" || role === "icon")
    return "Иконка шаблона: сохраняется без генерации";
  if (slot.protected || role === "brand")
    return "Логотип или служебный элемент: сохраняется";
  if (role === "decoration") return "Декоративный элемент: сохраняется";
  const b = slot.box;
  const w = Math.max(
    0,
    Math.min(dimensions.width, b.x + b.w) - Math.max(0, b.x),
  );
  const h = Math.max(
    0,
    Math.min(dimensions.height, b.y + b.h) - Math.max(0, b.y),
  );
  if (
    !dimensions.width ||
    !dimensions.height ||
    (w * h) / (dimensions.width * dimensions.height) < 0.012
  )
    return "Маленький элемент шаблона: сохраняется без генерации";
  return undefined;
}
