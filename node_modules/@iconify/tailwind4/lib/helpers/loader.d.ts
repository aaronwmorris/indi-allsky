import type { IconifyJSON } from '@iconify/types';
import type { IconifyIconSetSource } from './options.js';
/**
 * Locate icon set
 */
interface LocatedIconSet {
    main: string;
    info?: string;
}
export declare function locateIconSet(prefix: string): LocatedIconSet | undefined;
/**
 * Load icon set from source
 */
export declare function loadIconSet(source: IconifyIconSetSource): IconifyJSON | undefined;
export {};
