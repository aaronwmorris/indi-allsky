import { FactoryIconData } from "./types/data.js";
import { ComponentFactoryOptions } from "./types/options.js";
import { FactoryGeneratedComponent } from "./types/component.js";
/**
 * Create raw component code
 */
declare function createRawComponent(data: FactoryIconData, options: ComponentFactoryOptions): FactoryGeneratedComponent;
export { createRawComponent };