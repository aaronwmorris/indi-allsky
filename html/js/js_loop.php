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


header("content-type: application/json");

class GetImageData {
    public $db_uri = 'sqlite:/var/lib/indi-allsky/indi-allsky.sqlite';

    public $cameraId = 1;

    public $limit;
    private $_limit_default = 40;

    private $_hours = '-2 HOURS';
    private $_sqm_history = '-30 MINUTES';
    private $_stars_history = '-30 MINUTES';

    public $rootpath = '/var/www/html/allsky/';  # this needs to end with /

    private $_conn;


    public function __construct() {
        $this->_conn = $this->_dbConnect();

        # fetch the latest camera to connect
        $stmt_camera = $this->_conn->prepare("SELECT camera.id AS camera_id FROM camera ORDER BY camera.connectDate DESC LIMIT 1");
        $stmt_camera->execute();
        $camera_row = $stmt_camera->fetch();
        $this->cameraId = $camera_row['camera_id'];

        #if (isset($_GET['cameraId'])) {
        #    $cameraId = htmlspecialchars($_GET['cameraId']);

        #    if (filter_var($cameraId, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1, 'max_range' => 100]])) {
        #        # If this fails the default is used
        #        $this->cameraId = intval($cameraId);
        #    }
        #}

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


    private function _dbConnect() {
        $conn = new PDO($this->db_uri);
        $conn->exec('PRAGMA journal_mode=WAL');
        return($conn);
    }


    public function getLatestImages() {
        $data = array();
        $image_list = array();

        $query_date = new DateTime('now');
        $query_date->modify($this->_hours);

        # fetch files
        $stmt_files = $this->_conn->prepare("SELECT image.filename AS image_filename, image.sqm AS image_sqm, image.stars AS image_stars FROM image JOIN camera ON camera.id = image.camera_id WHERE camera.id = :cameraId AND image.createDate > :date ORDER BY image.createDate DESC LIMIT :limit");
        $stmt_files->bindParam(':cameraId', $this->cameraId, PDO::PARAM_INT);
        $stmt_files->bindParam(':date', $query_date->format('Y-m-d H:M:S'), PDO::PARAM_STR);
        $stmt_files->bindParam(':limit', $this->limit, PDO::PARAM_INT);
        $stmt_files->execute();

        while($row = $stmt_files->fetch()) {
            $filename = $row['image_filename'];
            $sqm = $row['image_sqm'];
            $stars = $row['image_stars'];

            if (! file_exists($filename)) {
                continue;
            }

            $relpath = str_replace($this->rootpath, '', $filename);

            $image_list[] = array(
                'file' => $relpath,
                'sqm' => $sqm,
                'stars' => $stars,
            );
        }

        return($image_list);
    }


    public function getSqmData() {
        $sqm_data = array();

        $query_date = new DateTime('now');
        $query_date->modify($this->_hours);

        # fetch sqm stats
        $stmt_sqm = $this->_conn->prepare("SELECT max(image.sqm) AS image_max_sqm, min(image.sqm) AS image_min_sqm, avg(image.sqm) AS image_avg_sqm FROM image JOIN camera ON camera.id = image.camera_id WHERE camera.id = :cameraId AND image.createDate > :date");
        $stmt_sqm->bindParam(':cameraId', $this->cameraId, PDO::PARAM_INT);
        $stmt_sqm->bindParam(':date', $query_date->format('Y-m-d H:M:S'), PDO::PARAM_STR);
        $stmt_sqm->execute();

        $row = $stmt_sqm->fetch();

        $sqm_data['max'] = $row['image_max_sqm'];
        $sqm_data['min'] = $row['image_min_sqm'];
        $sqm_data['avg'] = $row['image_avg_sqm'];


        return($sqm_data);
    }


    public function getStarsData() {
        $stars_data = array();

        $query_date = new DateTime('now');
        $query_date->modify($this->_hours);

        # fetch sqm stats
        $stmt_stars = $this->_conn->prepare("SELECT max(image.stars) AS image_max_stars, min(image.stars) AS image_min_stars, avg(image.stars) AS image_avg_stars FROM image JOIN camera ON camera.id = image.camera_id WHERE camera.id = :cameraId AND image.createDate > :date");
        $stmt_stars->bindParam(':cameraId', $this->cameraId, PDO::PARAM_INT);
        $stmt_stars->bindParam(':date', $query_date->format('Y-m-d H:M:S'), PDO::PARAM_STR);
        $stmt_stars->execute();

        $row = $stmt_stars->fetch();

        $stars_data['max'] = $row['image_max_stars'];
        $stars_data['min'] = $row['image_min_stars'];
        $stars_data['avg'] = $row['image_avg_stars'];


        return($stars_data);
    }


}

$x = new GetImageData();

$json_data = array();
$json_data['image_list'] = $x->getLatestImages();
$json_data['sqm_data'] = $x->getSqmData();
$json_data['stars_data'] = $x->getStarsData();

print(json_encode($json_data));
?>
