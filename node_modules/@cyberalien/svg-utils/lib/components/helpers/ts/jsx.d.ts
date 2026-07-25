import { FactoryIconData } from "../../types/data.js";
import { ComponentFactoryOptions } from "../../types/options.js";
import { GeneratedAssetFile } from "../../types/component.js";
import { FactoryComponentProps } from "../props/types.js";
import { JSXMode } from "../../types/jsx.js";
interface Options extends ComponentFactoryOptions {
  jsx: JSXMode;
}
/**
 * Add JSX component types
 */
declare function addJSXComponentTypes(data: FactoryIconData, options: Options, assets: GeneratedAssetFile[], props: FactoryComponentProps): string;
export { addJSXComponentTypes };