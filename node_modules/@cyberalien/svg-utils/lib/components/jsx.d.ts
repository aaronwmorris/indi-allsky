import { FactoryIconData } from "./types/data.js";
import { ComponentFactoryOptions } from "./types/options.js";
import { FactoryGeneratedComponent } from "./types/component.js";
import { JSXMode } from "./types/jsx.js";
interface Options extends ComponentFactoryOptions {
  jsx: JSXMode;
  fallbackPackage?: string;
  ts?: boolean;
}
/**
 * Create React component code
 */
declare function createJSXComponent(data: FactoryIconData, options: Options): FactoryGeneratedComponent;
export { createJSXComponent };