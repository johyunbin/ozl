// 미리보기용과 공개용을 가른다. 빌드 때 OZL_BUILD_MODE 를 읽는다.
export type Mode = "preview" | "public";
export const MODE: Mode = process.env.OZL_BUILD_MODE === "public" ? "public" : "preview";
export const IS_PREVIEW = MODE === "preview";
export const IS_PUBLIC = MODE === "public";
