<?php

set_error_handler('errHandle');
function errHandle($errNo, $errStr, $errFile, $errLine) {
    $date = date("Y-m-d h:m:s");
    $hostname = gethostname();

    $msg = sprintf('[%s-%s]: %s', $date, $hostname, $errStr);

    if ($errNo == E_NOTICE || $errNo == E_WARNING) {
        $errmsg = sprintf('%s in %s on line %d', $msg, $errFile, $errLine);
        throw new ErrorException($errmsg, $errNo);
    } else {
        error_log($msg);
    }
}


header("content-type: application/x-javascript");

class GetLatestImages {
    public $image_dir_base = '.';
    public $image_ext = array('jpg', 'jpeg', 'png');

    public function main() {
        $image_list = array();

        # current hour
        $now = strtotime('now');

        # day
        $day_now = strtotime('now');
        $day_current_Ymd = date('Ymd', $day_now);
        $day_current_d_H = date('d_H', $now);  // hour is not offset
        $day_current_hour_dir = join(DIRECTORY_SEPARATOR, array($this->image_dir_base, $day_current_Ymd, 'day', $day_current_d_H));
        $this->_getFolderFilesByExt($day_current_hour_dir, $image_list);

        # night
        $night_now = strtotime('-12 hours');
        $night_current_Ymd = date('Ymd', $night_now);
        $night_current_d_H = date('d_H', $now);  // hour is not offset
        $night_current_hour_dir = join(DIRECTORY_SEPARATOR, array($this->image_dir_base, $night_current_Ymd, 'night', $night_current_d_H));

        $this->_getFolderFilesByExt($night_current_hour_dir, $image_list);



        # last hour
        $minus_1h = strtotime('-1 hours');

        # day
        $day_minus_1h = strtotime('-1 hours');
        $day_minus_1h_Ymd = date('Ymd', $day_minus_1h);
        $day_minus_1h_d_H = date('d_H', $minus_1h);  // hour is not offset
        $day_minus_1h_dir = join(DIRECTORY_SEPARATOR, array($this->image_dir_base, $day_minus_1h_Ymd, 'day', $day_minus_1h_d_H));

        $this->_getFolderFilesByExt($day_minus_1h_dir, $image_list);


        # night
        $night_minus_1h = strtotime('-12 hours');
        $night_minus_1h_Ymd = date('Ymd', $night_minus_1h);
        $night_minus_1h_d_H = date('d_H', $minus_1h);  // hour is not offset
        $night_minus_1h_dir = join(DIRECTORY_SEPARATOR, array($this->image_dir_base, $night_minus_1h_Ymd, 'night', $night_minus_1h_d_H));
        $this->_getFolderFilesByExt($night_minus_1h_dir, $image_list);


        # sort oldest to newest
        usort($image_list, function($x, $y) { return filemtime($x) > filemtime($y); });

        #array_splice($image_list, 0, -50);  # get last 50 images

        return($image_list);
    }


    private function _getFolderFilesByExt($folder, &$r_image_list) {
        if (! is_dir($folder)) {
            error_log(sprintf('Folder not found: %s', $folder));
            return;
        }

        $h_dir = opendir($folder);

        while (false !== ($entry = readdir($h_dir))) {
            if ($entry == "." || $entry == "..") {
                continue;
            }

            $entry_path = join(DIRECTORY_SEPARATOR, array($folder, $entry));

            if (is_dir($entry_path)) {
                # recursion
                $this->_getFolderFilesByExt($entry_path, $r_image_list);
            }

            if (is_file($entry_path)) {
                foreach ($this->image_ext as $ext) {
                    $re = sprintf('/.%s$/', $ext);
                    if (preg_match($re, $entry)) {
                        array_push($r_image_list, $entry_path);
                        break;
                    }
                }
            }

        }

        closedir($h_dir);
    }

}

$x = new GetLatestImages();
$image_list = $x->main();

print('function getImages(maxImages) {');
print(' var image_list = ' . json_encode($image_list) . ';');
print('  while (image_list.length > maxImages) {');
print('   image_list.splice(0, 1);');
print('  };');
print(' return(image_list);');
print('}');
?>
