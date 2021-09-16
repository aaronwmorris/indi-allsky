<?php

#error_reporting(E_ALL);
#ini_set('error_reporting', E_ALL);
#ini_set('display_errors', 1);


#set_error_handler('errHandle');
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
    public $db_uri = 'sqlite:/var/lib/indi-allsky/indi-allsky.sqlite';

    private $_hours = '-2 HOURS';
    private $_limit = 100;

    public $rootpath = '/var/www/html/allsky/';  # this needs to end with /


    public function main() {
        $image_list = array();

        $conn = new PDO($this->db_uri);
        $stmt = $conn->prepare("SELECT filename FROM image WHERE datetime > datetime(datetime('now'), :hours) ORDER BY datetime DESC LIMIT :limit");
        $stmt->bindParam(':hours', $this->_hours, PDO::PARAM_STR);
        $stmt->bindParam(':limit', $this->_limit, PDO::PARAM_INT);
        $stmt->execute();

        while($row = $stmt->fetch()) {
            $filename = $row['filename'];

            if (! file_exists($filename)) {
                continue;
            }

            $relpath = str_replace($this->rootpath, '', $filename);

            $image_list[] = $relpath;
        }

        return($image_list);
    }

}

$x = new GetLatestImages();
$image_list = $x->main();

print('image_list = ' . json_encode($image_list) . ';');
?>
