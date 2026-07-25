import type { PreparsedIconifyPluginOptions } from '../helpers/options.js';
/**
 * Get CSS rules for main plugin (components)
 */
export declare function getCSSComponentsForPlugin(options: PreparsedIconifyPluginOptions): Record<string, Record<string, string>>;
/**
 * Get CSS rules for main plugin (utilities)
 */
export declare function getCSSRulesForPlugin(options: PreparsedIconifyPluginOptions): Record<string, Record<string, string>>;
