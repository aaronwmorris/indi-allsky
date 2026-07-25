import { IconViewBox } from "../../../svg/viewbox/types.js";
import { ComponentFactoryRenderingOptions } from "../../types/options.js";
interface SizeResult {
  width: string;
  height: string;
}
/**
 * Get size values for component
 */
declare function getComponentSizeValues(options: Pick<ComponentFactoryRenderingOptions, 'width' | 'height' | 'square'>, viewBox: IconViewBox): SizeResult | undefined;
export { getComponentSizeValues };