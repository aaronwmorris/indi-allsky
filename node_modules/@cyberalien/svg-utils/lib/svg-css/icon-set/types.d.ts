import { IconViewBox } from "../../svg/viewbox/types.js";
import { IconStatesList } from "../states/types.js";
/**
 * Icon entry in an icon set
 */
interface SVGCSSIconSetIcon {
  content: string;
  viewBox: IconViewBox | string | number;
  fallback?: string;
  states?: IconStatesList | number;
}
/**
 * Stateful class data
 */
interface SVGCSSIconSetClassData {
  r?: string | number;
  a?: string | number;
  sr?: Record<string, string | number>;
  t?: string | number;
  st?: Record<string, string | number>;
}
/**
 * Shared data for icons, which can be reused in multiple icons
 */
interface SVGCSSIconSetSharedData {
  classes?: Record<string, SVGCSSIconSetClassData>;
  keyframes?: Record<string, string>;
  css?: Partial<Record<keyof SVGCSSIconSetClassData, string[]>>;
  viewBoxes?: (IconViewBox | string)[];
  statesList?: IconStatesList[];
}
/**
 * Icon set in SVG+CSS format
 *
 * Does not include metadata
 */
interface SVGCSSIconSet extends SVGCSSIconSetSharedData {
  version: 1;
  fallbackPrefix?: string;
  icons: Record<string, SVGCSSIconSetIcon>;
  aliases?: Record<string, string>;
}
export { SVGCSSIconSet, SVGCSSIconSetClassData, SVGCSSIconSetIcon, SVGCSSIconSetSharedData };