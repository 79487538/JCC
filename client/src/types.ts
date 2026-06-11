export type Recommendation = {
  action: string;
  target?: string;
  item?: string;
  reason: string;
};

export type AnalyzeResponse = {
  status: string;
  recommendations: Recommendation[];
  model_used?: string;
  estimated_cost_usd?: number;
  ai_status?: string;
  ai_error?: string | null;
};

export type GameState = {
  level: number;
  gold: number;
  hp: number;
  round: string;
  shop: string[];
  board: string[];
  bench: string[];
  items: string[];
  god_choices: string[];
  selected_gods: string[];
  main_god: string | null;
  preferred_model: string;
};

export type ScreenshotSource = {
  id: string;
  name: string;
  thumbnailDataUrl: string;
};

export type ScreenshotCapture = {
  filePath: string;
  sourceId: string;
  sourceName: string;
  dataUrl: string;
};

declare global {
  interface Window {
    screenshotAPI?: {
      listSources: () => Promise<ScreenshotSource[]>;
      captureSource: (sourceId: string) => Promise<ScreenshotCapture>;
    };
  }
}
