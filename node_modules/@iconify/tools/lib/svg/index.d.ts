import { ParsedXMLTagElement } from "@cyberalien/svg-utils";
import { IconifyIcon } from "@iconify/types";
import { IconifyIconCustomisations } from "@iconify/utils/lib/customisations/defaults";
import { IconViewBox } from "@cyberalien/svg-utils/lib/svg/viewbox/types.js";
type ViewBox = IconViewBox;
/**
 * SVG class, used to manipulate icon content.
 */
declare class SVG {
  $svg: ParsedXMLTagElement;
  viewBox: ViewBox;
  /**
   * Constructor
   */
  constructor(content: string);
  /**
   * Get SVG as string
   */
  toString(customisations?: IconifyIconCustomisations, prettyPrint?: boolean): string;
  /**
   * Get SVG as string without whitespaces
   */
  toMinifiedString(customisations?: IconifyIconCustomisations): string;
  /**
   * Get SVG as string with whitespaces
   */
  toPrettyString(customisations?: IconifyIconCustomisations): string;
  /**
   * Get body
   */
  getBody(): string;
  /**
   * Get icon as IconifyIcon
   */
  getIcon(): IconifyIcon;
  /**
   * Load SVG
   *
   * @param {string} content
   */
  load(content: string): void;
}
export { type IconifyIcon, type IconifyIconCustomisations, SVG, type ViewBox };