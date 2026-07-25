import { SVGCSSIconSetClassData } from "../types.js";
declare const iconSetMinifySimpleKeys: (keyof Pick<SVGCSSIconSetClassData, 'r' | 'a' | 't'>)[];
declare const iconSetMinifyStatefulKeys: (keyof Pick<SVGCSSIconSetClassData, 'sr' | 'st'>)[];
declare const iconSetMinifyKeys: (keyof SVGCSSIconSetClassData)[];
export { iconSetMinifyKeys, iconSetMinifySimpleKeys, iconSetMinifyStatefulKeys };