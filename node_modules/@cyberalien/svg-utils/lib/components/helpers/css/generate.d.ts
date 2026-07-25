import { CSSGeneratedStylesheet } from "../../../css/types.js";
import { ComponentFactorySource } from "../../types/source.js";
import { ComponentFactoryOptions } from "../../types/options.js";
import { GeneratedAssetFile } from "../../types/component.js";
import { FactoryComponentImports } from "../imports/types.js";
interface Options extends Pick<ComponentFactoryOptions, 'cssMode' | 'cssPath' | 'doubleDirsForCSS' | 'mergeCSS' | 'legacyCSS' | 'staticState'> {
  componentType?: 'svelte';
}
/**
 * Generate CSS files for component
 *
 * Adds imports to imports object, adds assets
 */
declare function generateCSSFilesForComponent(content: Omit<ComponentFactorySource, 'viewBox'>, imports: FactoryComponentImports, assets: GeneratedAssetFile[], options: Options): CSSGeneratedStylesheet | undefined;
export { generateCSSFilesForComponent };