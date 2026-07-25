import { createReadStream } from "node:fs";
import { unpackTar } from "modern-tar/fs";
import { createGunzip } from "node:zlib";
import { pipeline } from "node:stream/promises";

/**
* Unpack .tgz archive
*/
async function untar(file, path) {
	await pipeline(createReadStream(file, { highWaterMark: 256 * 1024 }), createGunzip(), unpackTar(path));
}

export { untar };