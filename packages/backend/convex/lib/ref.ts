// Fixed reference values shared by the backend and the web app. The extractor keeps the same
// lists in apps/extractor/src/rov_extractor (LANES in refdata.py, STAGES in models.py).

export const LANES = ["DSL", "JGL", "MID", "ADL", "SUP"] as const;
export type Lane = (typeof LANES)[number];

export const LANE_NAMES: Record<Lane, string> = {
  DSL: "Dark Slayer lane",
  JGL: "Jungle",
  MID: "Mid lane",
  ADL: "Abyssal Dragon lane",
  SUP: "Support",
};

export const STAGES = [
  { id: "regular", name: "Regular season" },
  { id: "leg1", name: "Leg 1" },
  { id: "leg2", name: "Leg 2" },
  { id: "playoffs", name: "Playoff" },
  { id: "final", name: "Final" },
] as const;

export const stageName = (id: string): string => STAGES.find((s) => s.id === id)?.name ?? id;
