type UnzipFilterCallback = (file: string) => boolean;
/**
 * Unzip archive
 */
declare function unzip(source: string, path: string, filter?: UnzipFilterCallback): Promise<void>;
export { UnzipFilterCallback, unzip };