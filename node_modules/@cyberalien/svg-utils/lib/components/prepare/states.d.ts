import { SVGCSSStatefulIcon } from "../../svg-css/icon/types.js";
import { ComponentFactorySource } from "../types/source.js";
import { ComponentFactoryStatefulIconRenderingOptions } from "../types/options.js";
/**
 * Check states for stateful icon
 */
declare function prepareComponentFactoryStatefulIcon(icon: SVGCSSStatefulIcon, options?: ComponentFactoryStatefulIconRenderingOptions): ComponentFactorySource | undefined;
export { prepareComponentFactoryStatefulIcon };