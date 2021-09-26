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

class GetImageData {
    public $db_uri = 'sqlite:/var/lib/indi-allsky/indi-allsky.sqlite';

    private $_hours = '-2 HOURS';
    private $_limit_default = 40;

    private $_sqm_history = '-30 MINUTES';

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


        $this->_conn = $this->_dbConnect();

    }


    private function _dbConnect() {
        $conn = new PDO($this->db_uri);
        return($conn);
    }


    public function getLatestImages() {
        $data = array();
        $image_list = array();

        # fetch files
        $stmt_files = $this->_conn->prepare("SELECT filename,sqm FROM image WHERE createDate > datetime(datetime('now'), :hours) ORDER BY createDate DESC LIMIT :limit");
        $stmt_files->bindParam(':hours', $this->_hours, PDO::PARAM_STR);
        $stmt_files->bindParam(':limit', $this->limit, PDO::PARAM_INT);
        $stmt_files->execute();

        while($row = $stmt_files->fetch()) {
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


    public function getSqmData() {
        $sqm_data = array();

        # fetch sqm stats
        $stmt_sqm = $this->_conn->prepare("SELECT max(sqm) AS max_sqm,min(sqm) as min_sqm FROM image WHERE createDate > datetime(datetime('now'), :hours)");
        $stmt_sqm->bindParam(':hours', $this->_sqm_history, PDO::PARAM_STR);
        $stmt_sqm->execute();

        $row = $stmt_sqm->fetch();

        $sqm_data['max'] = $row['max_sqm'];
        $sqm_data['min'] = $row['min_sqm'];


        return($sqm_data);
    }

}

$x = new GetImageData();
$image_list = $x->getLatestImages();
$sqm_data = $x->getSqmData();

print('image_list = ' . json_encode($image_list) . ';');
print('sqm_data = ' . json_encode($sqm_data) . ';');
?>
