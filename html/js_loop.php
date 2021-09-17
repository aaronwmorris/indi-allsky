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
    private $_limit_default = 40;

    public $rootpath = '/var/www/html/allsky/';  # this needs to end with /


    public function __construct() {
        if (isset($_GET['limit'])) {
            $limit = htmlspecialchars($_GET['limit']);

            if (filter_var($limit, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1, 'max_range' => 100]])) {
                $this->limit = intval($limit);
            } else {
                $this->limit = $this->_limit_default;
            }
        } else {
            $this->limit = $this->_limit_default;
        }
    }


    public function main() {
        $image_list = array();

        $conn = new PDO($this->db_uri);
        $stmt = $conn->prepare("SELECT filename,sqm FROM image WHERE datetime > datetime(datetime('now'), :hours) ORDER BY datetime DESC LIMIT :limit");
        $stmt->bindParam(':hours', $this->_hours, PDO::PARAM_STR);
        $stmt->bindParam(':limit', $this->limit, PDO::PARAM_INT);
        $stmt->execute();

        while($row = $stmt->fetch()) {
            $filename = $row['filename'];
            $sqm = $row['sqm'];

            if (! file_exists($filename)) {
                continue;
            }

            $relpath = str_replace($this->rootpath, '', $filename);

            $image_list[] = array(
                'file' => $relpath,
                'sqm' => $sqm,
            );
        }

        $r_image_list = array_reverse($image_list);

        return($r_image_list);
    }

}

$x = new GetLatestImages();
$image_list = $x->main();

print('image_list = ' . json_encode($image_list) . ';');
?>
