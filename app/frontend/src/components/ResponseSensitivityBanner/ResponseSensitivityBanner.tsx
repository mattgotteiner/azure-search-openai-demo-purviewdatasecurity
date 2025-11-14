import React from "react";
import { ResponseSensitivityInfo } from "../../api";
import { SensitivityBadge } from "../SensitivityBadge";
import styles from "./ResponseSensitivityBanner.module.css";

interface Props {
    sensitivity: ResponseSensitivityInfo;
}

export const ResponseSensitivityBanner: React.FC<Props> = ({ sensitivity }) => {
    const { overall_label } = sensitivity;

    return (
        <div className={styles.container}>
            <span className={styles.title}>Response sensitivity label</span>
            <SensitivityBadge label={overall_label} />
        </div>
    );
};
