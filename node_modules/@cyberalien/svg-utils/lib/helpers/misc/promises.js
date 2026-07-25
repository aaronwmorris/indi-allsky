import { compareKeys } from "./keys.js";
let cache = [];
/**
* Make sure multiple instances of Promise or callback are not ran at the same time
*/
function uniquePromise(key, callback) {
	return new Promise((resolve, reject) => {
		const cachedItem = cache.find((item) => compareKeys(key, item.key));
		if (cachedItem) {
			cachedItem.callbacks.push({
				resolve,
				reject
			});
			return;
		}
		const newItem = {
			key,
			callbacks: [{
				resolve,
				reject
			}]
		};
		cache.push(newItem);
		function done(success, result) {
			cache = cache.filter((item) => item !== newItem);
			newItem.callbacks.forEach((item) => {
				try {
					if (success) item.resolve(result);
					else item.reject(result);
				} catch (err2) {}
			});
		}
		let cb;
		try {
			cb = callback();
		} catch (err) {
			done(false, err);
			return;
		}
		if (cb instanceof Promise) cb.then((data) => {
			done(true, data);
		}).catch((err) => {
			done(false, err);
		});
		else done(true, cb);
	});
}
export { uniquePromise };
