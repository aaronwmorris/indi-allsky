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

class GetChartData {
    public $db_uri = 'sqlite:/var/lib/indi-allsky/indi-allsky.sqlite';

    public $cameraId = 1;

    public $limit;
    private $_limit_default = 40;

    private $_hours = '-30 MINUTES';

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


    public function getLatestChartData() {
        $data = array();
        $chart_data = array();

        $query_date = new DateTime('now');
        $query_date->modify($this->_hours);

        $stmt_files = $this->_conn->prepare("SELECT image.sqm AS image_sqm, image.createDate AS image_createDate FROM image JOIN camera ON camera.id = image.camera_id WHERE camera.id = :cameraId AND image.createDate > :date ORDER BY image.createDate DESC");
        $stmt_files->bindParam(':cameraId', $this->cameraId, PDO::PARAM_INT);
        $stmt_files->bindParam(':date', $query_date->format('Y-m-d H:M:S'), PDO::PARAM_STR);
        $stmt_files->execute();

        while($row = $stmt_files->fetch()) {
            $sqm = $row['image_sqm'];
            $createDate = new DateTime($row['image_createDate']);

            $chart_data[] = array(
                'x' => date_format($createDate, 'H:i:s'),
                'y' => $sqm,
            );
        }

        $r_chart_data = array_reverse($chart_data);

        return($r_chart_data);
    }

}

$x = new GetChartData();

$json_data = array();
$json_data['chart_data'] = $x->getLatestChartData();

print(json_encode($json_data));
?>
