import { FactoryIconData } from "./types/data.js";
import { ComponentFactoryOptions } from "./types/options.js";
import { FactoryGeneratedComponent } from "./types/component.js";
interface Options extends ComponentFactoryOptions {
  ts?: boolean;
}
/**
 * Create Solid component code
 */
declare function createSolidComponent(data: FactoryIconData, options: Options): FactoryGeneratedComponent;
export { createSolidComponent };