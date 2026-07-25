import { FactoryIconData } from "./types/data.js";
import { ComponentFactoryOptions } from "./types/options.js";
import { FactoryGeneratedComponent } from "./types/component.js";
/**
 * Create Astro component code
 */
declare function createAstroComponent(data: FactoryIconData, options: ComponentFactoryOptions): FactoryGeneratedComponent;
export { createAstroComponent };