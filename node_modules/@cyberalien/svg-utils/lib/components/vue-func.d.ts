import { FactoryIconData } from "./types/data.js";
import { ComponentFactoryOptions } from "./types/options.js";
import { FactoryGeneratedComponent } from "./types/component.js";
/**
 * Create functional Vue component code
 */
declare function createVueFunctionalComponent(data: FactoryIconData, options: ComponentFactoryOptions): FactoryGeneratedComponent;
export { createVueFunctionalComponent };