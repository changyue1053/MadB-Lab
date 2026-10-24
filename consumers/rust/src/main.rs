use madb_c_client::{Client, Error};

fn main() {
    let mode = std::env::args().nth(1).expect("case name is required");
    if mode == "abi-mismatch" {
        assert!(matches!(Client::connect(), Err(Error::AbiMismatch)));
    } else if mode == "profile-mismatch" {
        assert!(matches!(Client::connect(), Err(Error::ProfileMismatch)));
    } else {
        let client = Client::connect().expect("candidate bootstrap must match before business calls");
        match mode.as_str() {
            "data" => {
                assert_eq!(client.checksum(&[]).unwrap(), 0);
                assert_eq!(client.checksum(&[0, 1, 127, 128, 255]).unwrap(), 511);
                assert_eq!(client.checksum(&vec![255; 65536]).unwrap(), 16_711_680);
                assert!(matches!(client.checksum(&vec![0; 65537]), Err(Error::Native { status: 1, domain: 0, code: 0 })));
            }
            "bootstrap" => {}
            _ => panic!("unknown case {mode}"),
        }
    }
    println!("{{\"result\":\"passed\"}}");
}
