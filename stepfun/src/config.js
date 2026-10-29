export const MODEL = "Xenova/all-MiniLM-L6-v2";
export const REVISION = "751bff37182d3f1213fa05d7196b954e230abad9";
export const DIMENSION = 384;
export const PRECISIONS = ["q8", "fp32"];
export const signature = (dtype) =>
  `${MODEL}@${REVISION}:${dtype}:mean:normalized:384`;
