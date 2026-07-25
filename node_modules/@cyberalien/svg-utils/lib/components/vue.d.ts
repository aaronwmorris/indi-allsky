import { FactoryIconData } from "./types/data.js";
import { ComponentFactoryOptions } from "./types/options.js";
import { FactoryGeneratedComponent } from "./types/component.js";
interface VueOptions extends ComponentFactoryOptions {
  ts?: boolean;
}
/**
 * Create Vue component code
 */
declare function createVueComponent(data: FactoryIconData, options: VueOptions): FactoryGeneratedComponent;
export { createVueComponent };