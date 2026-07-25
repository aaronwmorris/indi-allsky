import { SVG } from "../svg/index.js";
import { Color } from "@iconify/utils/lib/colors/types";
type ColorCallback = (value: string, color: Color | null) => boolean;
type ColorCheck = string | string[] | ColorCallback;
interface SVGToMaskOptions {
  color?: string;
  solid?: ColorCheck;
  transparent?: ColorCheck;
  custom?: (value: string, color: Color | null) => string | number | undefined;
  force?: boolean;
  id?: string;
}
/**
 * Converts SVG to mask
 *
 * Fixes badly designed icons, which use white shape where icon supposed to be transparent
 */
declare function convertSVGToMask(svg: SVG, options?: SVGToMaskOptions): boolean;
export { convertSVGToMask };