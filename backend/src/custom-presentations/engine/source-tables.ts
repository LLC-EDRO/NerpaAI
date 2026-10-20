import type {Layout} from './domain.js';
export const maxTableRows = 10;

export const maxTableDataRows = maxTableRows - 1;

export function regularTables(layout: Layout) {
  const ids = [
    ...new Set(layout.slots.filter((s) => s.cell).map((s) => s.shapeId)),
  ];
  return ids.flatMap((shapeId) => {
    const slots = layout.slots.filter((s) => s.shapeId === shapeId && s.cell);
    const rowCount = Math.max(...slots.map((s) => s.cell[0])) + 1;
    const columnCount = Math.max(...slots.map((s) => s.cell[1])) + 1;
    const at = (r: number, c: number) =>
      slots.find((s) => s.cell[0] === r && s.cell[1] === c);
    if (
      rowCount < 2 ||
      columnCount < 2 ||
      columnCount > 8 ||
      slots.length !== rowCount * columnCount
    )
      return [];
    for (let r = 0; r < rowCount; r++)
      for (let c = 0; c < columnCount; c++) {
        const s = at(r, c),
          column = at(0, c),
          row = at(r, 0);
        if (
          !s ||
          !column ||
          !row ||
          s.key !== `s${shapeId}_r${r}_c${c}` ||
          Math.abs(s.x - column.x) > 0.1 ||
          Math.abs(s.w - column.w) > 0.1 ||
          Math.abs(s.y - row.y) > 0.1 ||
          Math.abs(s.h - row.h) > 0.1
        )
          return [];
      }
    const top = at(1, 0)!.y;
    const bodyHeight = Math.max(...slots.map((s) => s.y + s.h)) - top;
    const font = Math.max(
      ...slots.filter((s) => s.cell[0] > 0).map((s) => s.size),
    );
    return [
      {
        shapeId,
        columnCount,
        rowCount,
        bodyHeight,
        maxDataRows: Math.min(maxTableDataRows, Math.max(
          rowCount - 1, Math.floor(bodyHeight / (font * 2.5 + 8)), 1,
        )),
        headers: slots
          .filter((s) => s.cell[0] === 0)
          .sort((a, b) => a.cell[1] - b.cell[1])
          .map((s) => s.text),
      },
    ];
  });
}

/** Generated from the actual native grid, never a per-template schema. */
