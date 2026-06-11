import { createWorker, type Worker } from "tesseract.js";
import type { GameState, ScreenshotCapture, ScreenshotSource } from "../types";

export type RecognitionField =
  | "level"
  | "gold"
  | "hp"
  | "round"
  | "shop"
  | "board"
  | "bench"
  | "items"
  | "god_choices";

export type RecognitionRegion = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type FieldRecognitionResult = {
  field: RecognitionField;
  text: string;
  confidence: number;
  parsed: GameState[RecognitionField];
  fallback_used: boolean;
};

export type RecognizedGameState = GameState & {
  screenshot_path?: string;
  source_name?: string;
  field_results: Record<RecognitionField, FieldRecognitionResult>;
};

export const recognitionFields: RecognitionField[] = [
  "level",
  "gold",
  "hp",
  "round",
  "shop",
  "board",
  "bench",
  "items",
  "god_choices",
];

export const defaultRegions: Record<RecognitionField, RecognitionRegion> = {
  level: { x: 40, y: 40, width: 120, height: 50 },
  gold: { x: 160, y: 40, width: 140, height: 50 },
  hp: { x: 300, y: 40, width: 120, height: 50 },
  round: { x: 830, y: 40, width: 140, height: 50 },
  shop: { x: 360, y: 780, width: 760, height: 180 },
  board: { x: 360, y: 220, width: 760, height: 360 },
  bench: { x: 330, y: 600, width: 820, height: 110 },
  items: { x: 1180, y: 220, width: 260, height: 360 },
  god_choices: { x: 1120, y: 600, width: 360, height: 220 },
};

export const defaultRecognizedState: GameState = {
  level: 6,
  gold: 32,
  hp: 78,
  round: "3-5",
  shop: ["卡莎", "慎", "阿狸", "亚索", "妮蔻"],
  board: ["盖伦2", "阿狸1", "慎1"],
  bench: ["亚索1", "妮蔻1"],
  items: ["反曲弓", "大棒", "锁子甲"],
  god_choices: ["索拉卡", "锤石"],
  selected_gods: ["索拉卡"],
  main_god: null,
  preferred_model: "auto",
};

const knownChampions = ["卡莎", "慎", "阿狸", "亚索", "妮蔻", "盖伦"];
const knownItems = ["反曲弓", "大棒", "锁子甲", "女神泪", "拳套", "暴风大剑"];
const knownGods = ["索拉卡", "锤石"];

export async function listScreenshotSources(): Promise<ScreenshotSource[]> {
  if (!window.screenshotAPI) {
    throw new Error("Electron screenshot API is unavailable. Use npm run electron:dev.");
  }
  return window.screenshotAPI.listSources();
}

export async function captureScreenshot(sourceId: string): Promise<ScreenshotCapture> {
  if (!window.screenshotAPI) {
    throw new Error("Electron screenshot API is unavailable. Use npm run electron:dev.");
  }
  return window.screenshotAPI.captureSource(sourceId);
}

export function loadRegions(): Record<RecognitionField, RecognitionRegion> {
  const raw = localStorage.getItem("screenshotRecognitionRegions");
  if (!raw) {
    return defaultRegions;
  }
  try {
    return { ...defaultRegions, ...JSON.parse(raw) };
  } catch {
    return defaultRegions;
  }
}

export function saveRegions(regions: Record<RecognitionField, RecognitionRegion>) {
  localStorage.setItem("screenshotRecognitionRegions", JSON.stringify(regions));
}

async function cropDataUrl(dataUrl: string, region: RecognitionRegion): Promise<string> {
  const image = new Image();
  image.src = dataUrl;
  await image.decode();

  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, region.width);
  canvas.height = Math.max(1, region.height);
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Canvas is unavailable");
  }

  context.drawImage(
    image,
    region.x,
    region.y,
    region.width,
    region.height,
    0,
    0,
    region.width,
    region.height,
  );
  return canvas.toDataURL("image/png");
}

async function recognizeRegion(worker: Worker, dataUrl: string, region: RecognitionRegion) {
  const cropped = await cropDataUrl(dataUrl, region);
  const result = await worker.recognize(cropped);
  return {
    text: result.data.text.trim(),
    confidence: Math.round(result.data.confidence || 0),
  };
}

function parseNumber(text: string, fallback: number) {
  const match = text.replace(/\s+/g, "").match(/(\d+)/);
  return match ? Number(match[1]) : fallback;
}

function parseRound(text: string, fallback: string) {
  const match = text.match(/([1-9]\s*[-—]\s*[1-9])/);
  return match ? match[1].replace(/\s+/g, "").replace("—", "-") : fallback;
}

function parseKnownList(text: string, knownValues: string[], fallback: string[]) {
  const found = knownValues.filter((value) => text.includes(value));
  return found.length > 0 ? found : fallback;
}

function parseField(field: RecognitionField, text: string): GameState[RecognitionField] {
  switch (field) {
    case "level":
      return parseNumber(text, defaultRecognizedState.level);
    case "gold":
      return parseNumber(text, defaultRecognizedState.gold);
    case "hp":
      return parseNumber(text, defaultRecognizedState.hp);
    case "round":
      return parseRound(text, defaultRecognizedState.round);
    case "shop":
      return parseKnownList(text, knownChampions, defaultRecognizedState.shop).slice(0, 5);
    case "board":
      return parseKnownList(text, knownChampions, ["盖伦", "阿狸", "慎"])
        .slice(0, 6)
        .map((name, index) => `${name}${index === 0 ? 2 : 1}`);
    case "bench":
      return parseKnownList(text, ["亚索", "妮蔻", "慎", "阿狸"], defaultRecognizedState.bench).map((name) =>
        /\d$/.test(name) ? name : `${name}1`,
      );
    case "items":
      return parseKnownList(text, knownItems, defaultRecognizedState.items);
    case "god_choices":
      return parseKnownList(text, knownGods, defaultRecognizedState.god_choices);
  }
}

function isFallback(field: RecognitionField, text: string, confidence: number) {
  if (!text.trim() || confidence < 35) {
    return true;
  }
  const parsed = parseField(field, text);
  const fallback = defaultRecognizedState[field];
  return JSON.stringify(parsed) === JSON.stringify(fallback) && !text.includes(String(parsed));
}

export async function recognizeGameStateFromScreenshot(
  sourceId: string,
  preferredModel: string,
  regions: Record<RecognitionField, RecognitionRegion>,
): Promise<RecognizedGameState> {
  const capture = await captureScreenshot(sourceId);
  const worker = await createWorker("chi_sim+eng");
  const fieldResults = {} as Record<RecognitionField, FieldRecognitionResult>;

  try {
    for (const field of recognitionFields) {
      const { text, confidence } = await recognizeRegion(worker, capture.dataUrl, regions[field]);
      const fallbackUsed = isFallback(field, text, confidence);
      fieldResults[field] = {
        field,
        text,
        confidence,
        parsed: fallbackUsed ? defaultRecognizedState[field] : parseField(field, text),
        fallback_used: fallbackUsed,
      };
    }
  } finally {
    await worker.terminate();
  }

  return {
    level: fieldResults.level.parsed as number,
    gold: fieldResults.gold.parsed as number,
    hp: fieldResults.hp.parsed as number,
    round: fieldResults.round.parsed as string,
    shop: fieldResults.shop.parsed as string[],
    board: fieldResults.board.parsed as string[],
    bench: fieldResults.bench.parsed as string[],
    items: fieldResults.items.parsed as string[],
    god_choices: fieldResults.god_choices.parsed as string[],
    selected_gods: defaultRecognizedState.selected_gods,
    main_god: null,
    preferred_model: preferredModel,
    screenshot_path: capture.filePath,
    source_name: capture.sourceName,
    field_results: fieldResults,
  };
}
