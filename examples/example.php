<?php
# Example PHP to query indi-allsky database
# Requires packages
#   * php-sqlite3
#   * php-json

header("Content-Type: application/json");


class IndiAllSkyLatestImages {
    public $db_uri = 'sqlite:/var/lib/indi-allsky/indi-allsky.sqlite';
    public $cameraId = 2;
    public $limit = 1;

    public $rootpath = '/var/www/html/allsky/';  # this needs to end with /

    private $_conn;


    public function __construct() {
        $this->_conn = $this->_dbConnect();
    }

    private function _dbConnect() {
        $conn = new PDO($this->db_uri);
        $conn->exec('PRAGMA journal_mode=WAL');
        return($conn);
    }

    public function getLatestImages() {
        $stmt_files = $this->_conn->prepare("
            SELECT
                image.filename AS image_filename
            FROM image
            JOIN camera
                ON camera.id = image.camera_id
            WHERE
                camera.id = :cameraId
            ORDER BY
                image.createDate DESC
            LIMIT
                :limit
        ");
        $stmt_files->bindParam(':cameraId', $this->cameraId, PDO::PARAM_INT);
        $stmt_files->bindParam(':limit', $this->limit, PDO::PARAM_INT);
        $stmt_files->execute();


        $image_list = array();
        while($row = $stmt_files->fetch()) {
            $filename = $row['image_filename'];

            if (! file_exists($filename)) {
                continue;
            }

            $relpath = str_replace($this->rootpath, '', $filename);

            $image_list[] = $relpath;
        }

        return($image_list);
    }
}

$x = new IndiAllSkyLatestImages();

$json_data = $x->getLatestImages();

print(json_encode($json_data));
?>
