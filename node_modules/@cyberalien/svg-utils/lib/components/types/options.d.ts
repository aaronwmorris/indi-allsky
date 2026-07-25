import { UniqueHashPartialOptions } from "../../helpers/hash/types.js";
import { StatefulIconSelectorsConfig } from "../../svg-css/states/selector/types.js";
import { CSSExportMode } from "./css.js";
/**
 * Asset path, generated from configuration
 */
interface GeneratedAssetPath {
  filename: string;
  import: string;
}
/**
 * File system options for component factory
 */
interface ComponentFactoryFileSystemOptions {
  doubleDirsForCSS: boolean;
  prefixDirsForComponents: boolean | string;
  doubleDirsForComponents: boolean;
  rootPath: GeneratedAssetPath;
  cssPath: GeneratedAssetPath;
  helpersDirectory?: string;
  sharedTypes?: boolean;
}
/**
 * Rendering options for stateful icons
 */
interface ComponentFactoryStatefulIconRenderingOptions {
  stateSelectors?: StatefulIconSelectorsConfig;
  staticState?: boolean;
}
/**
 * Rendering options for component factory
 */
interface ComponentFactoryRenderingOptions extends ComponentFactoryStatefulIconRenderingOptions {
  square?: boolean;
  cssMode: CSSExportMode;
  legacyCSS?: boolean;
  mergeCSS?: GeneratedAssetPath;
  width?: string;
  height?: string;
}
/**
 * Options for component factory
 */
interface ComponentFactoryOptions extends ComponentFactoryFileSystemOptions, ComponentFactoryRenderingOptions, Pick<UniqueHashPartialOptions, 'context'> {}
export { ComponentFactoryFileSystemOptions, ComponentFactoryOptions, ComponentFactoryRenderingOptions, ComponentFactoryStatefulIconRenderingOptions, GeneratedAssetPath };