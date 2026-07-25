import { IconViewBox } from "../../../svg/viewbox/types.js";
import { IconStatesList } from "../../states/types.js";
import { createCompactContext } from "../../../helpers/data/compact.js";
import { SVGCSSIconSet } from "../types.js";
import { iconSetMinifyKeys } from "./keys.js";
type Keys = (typeof iconSetMinifyKeys)[number];
interface Context extends Record<Keys, ReturnType<typeof createCompactContext<string>>> {
  viewBox: ReturnType<typeof createCompactContext<IconViewBox | string>>;
  states: ReturnType<typeof createCompactContext<IconStatesList>>;
}
/**
 * Create context for minification
 */
declare function createIconSetMinifyContext(): Context;
/**
 * Minify icon set
 */
declare function minifySVGCSSIconSet(iconSet: SVGCSSIconSet): void;
export { createIconSetMinifyContext, minifySVGCSSIconSet };