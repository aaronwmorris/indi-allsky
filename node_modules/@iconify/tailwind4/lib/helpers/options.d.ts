import type { IconifyJSON } from '@iconify/types';
export type IconifyIconSetSource = IconifyJSON | string | (() => IconifyJSON);
/**
 * Common options
 */
export interface CommonIconifyPluginOptions {
    iconSets?: Record<string, IconifyIconSetSource>;
}
/**
 * Options for dynamic class names
 */
export interface DynamicIconifyPluginOptions extends CommonIconifyPluginOptions {
    prefix?: string;
    overrideOnly?: boolean;
    scale?: number;
}
/**
 * Types for main Iconify plugin
 */
export type IconsListOption = string[] | ((name: string) => boolean);
type IconSetSource = string | IconifyJSON;
interface IconSetOptions {
    prefix?: string;
    source?: IconSetSource;
    icons?: IconsListOption;
    customise?: (content: string, name: string) => string;
}
type IconifyPluginListOptions = (string | IconSetOptions)[];
/**
 * Options for main Iconify plugin
 */
export interface PreparsedIconifyPluginOptions extends CommonIconifyPluginOptions {
    iconSelector?: string;
    maskSelector?: string;
    backgroundSelector?: string;
    varName?: string;
    scale?: number;
    square?: boolean;
    prefixes?: IconifyPluginListOptions;
}
export {};
