import { IconSet } from "./index.js";
declare const paletteTags: {
  monotone: string;
  palette: string;
};
declare const sizeTags: {
  square: string;
  gridPrefix: string;
  heightPrefix: string;
};
/**
 * Add tags to icon set
 *
 * @deprecated
 */
declare function addTagsToIconSet(iconSet: IconSet, customTags?: string[]): string[];
export { addTagsToIconSet, paletteTags, sizeTags };