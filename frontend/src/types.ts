export type Study = {
  id: string;
  label: string;
  title: string;
  category: string;
  side: string;
  enabled: boolean;
  fetched: string | null;
  error: string | null;
};
export type Node = {
  id: string;
  parent: string;
  fen: string;
  san: string;
  label?: string;
  uci: string | null;
  depth: number;
  comment: string;
  starting_comment: string;
  nags: number[];
  children: string[];
};
export type Chapter = {
  id: string;
  study_id: string;
  remote_id: string;
  name: string;
  status: string;
  fetched: string;
  error: string | null;
  deleted: boolean;
  can_undo: boolean;
  can_redo: boolean;
  hash: string;
  pgn: string;
  tags: Record<string, string>;
  nodes: Node[];
};
export type Reference = {
  study_id: string;
  study: string;
  chapter_id: string;
  chapter: string;
  path: string;
  fen: string;
  comment: string;
  nags: number[];
  status: string;
  url: string;
  category: string;
};
export type Move = {
  uci: string;
  san: string;
  studies: number;
  chapters: number;
  occurrences: number;
  references: (Reference & { uci: string; san: string })[];
};
export type Explorer = {
  position: string;
  occurrences: Reference[];
  moves: Move[];
};
export type Preview = {
  token: string;
  status: string;
  local_diff: string;
  remote_diff: string;
  upload_diff: string;
  base: string;
  local: string;
  remote: string;
  warning: string;
  can_write: boolean;
};
export type Exercise = {
  done: boolean;
  token: string;
  fen: string;
  chapter_id: string;
  chapter: string;
  study: string;
};
export type Answer = {
  correct: boolean;
  moves: { uci: string; san: string; comment: string; nags: number[] }[];
  comment: string;
  due: string;
};
